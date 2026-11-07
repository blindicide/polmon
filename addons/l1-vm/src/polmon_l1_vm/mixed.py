"""Explicit VM selection alongside L0 endpoints and nested Linux namespaces.

All links belong to VMBackend's isolated lab. Only short-lived subprocesses enter
namespaces; the multithreaded parent never calls setns. SCM_RIGHTS transfers TAPs
and bound HTTP sockets back to that parent, not network access to the host.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import os
import secrets
import socket
import struct
import time
from dataclasses import replace
from pathlib import Path
from threading import Thread

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.hybrid.responder import TapResponder
from polmon.backends.hybrid.tap import TapPort
from polmon.backends.namespace.runner import stop_process_group
from polmon.topology.models import Node, NodeClass, Topology
from polmon_l1_vm.backend import VMBackend, addon_command
from polmon_l1_vm.host import alive, process_start
from polmon_l1_vm.images import VMError
from polmon_l1_vm.lab import Lab, _name, file_identity

MAX_L0 = 128
MAX_NAMESPACES = 8
HELPER_TIMEOUT = 10
HOLDER_SECONDS = 900


def subset(topology: Topology, nodes: list[Node]) -> Topology:
    # Preserve the address-space opt-in, UUIDs, names and layout coordinates.
    return Topology(
        id=topology.id, address_space=topology.address_space,
        networks=topology.networks, nodes=nodes,
    )


class MixedLab(Lab):
    def __init__(self, topology: Topology, runner, *, vm_nodes: frozenset[str], mode: str):
        super().__init__(topology, runner, mode=mode)
        self.names = replace(
            self.names,
            taps={key: name for key, name in self.names.taps.items() if key[0] in vm_nodes},
        )
        self.l0_taps = {
            interface.network: _name(f"mixed:{topology.id}:{interface.network}", "t")
            for node in topology.nodes if node.node_class == NodeClass.L0
            for interface in node.interfaces
        }
        self.veths = {
            (node.id, interface.id): (
                _name(f"mixed:{topology.id}:{node.id}:{interface.id}", "h"),
                _name(f"mixed:{topology.id}:{node.id}:{interface.id}", "p"),
            )
            for node in topology.nodes
            if node.node_class == NodeClass.L1 and node.id not in vm_nodes
            for interface in node.interfaces
        }
        self.extra_links = {
            *self.l0_taps.values(), *(p for pair in self.veths.values() for p in pair),
        }
        generated = [
            *self.names.bridges.values(), *self.names.taps.values(),
            *self.l0_taps.values(), *(p for pair in self.veths.values() for p in pair),
        ]
        if len(generated) != len(set(generated)):
            raise VMError("vm.mixed_unsupported")

    def _lines(self) -> list[str]:
        # Lab's full topology reserves probe addresses against ALL peers, but only
        # explicitly selected VMs receive per-interface TAPs.
        lines = super()._lines()
        owner = f" user {self.owner_uid} group {self.owner_gid}" if self.privileged else ""
        for network, tap in self.l0_taps.items():
            lines += [
                f"tuntap add dev {tap} mode tap{owner}",
                f"link set dev {tap} master {self.names.bridges[network]}",
                f"link set dev {tap} up",
            ]
        return lines


class _IdentityHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.server.identity if self.path == "/" else b"not found\n"
        self.send_response(200 if self.path == "/" else 404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class _IdentityServer(http.server.HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(1)  # A slow client cannot block teardown indefinitely.
        return connection, address


class MixedBackend(VMBackend):
    """Opt-in backend; unselected L1 continues to mean a Linux namespace."""

    name = "l1-vm-mixed-addon"

    def __init__(self, *, vm_nodes: list[str], **kwargs):
        super().__init__(**kwargs)
        if not vm_nodes or len(vm_nodes) != len(set(vm_nodes)):
            raise VMError("vm.mixed_unsupported")
        self.vm_nodes = frozenset(vm_nodes)
        self.full_topology: Topology | None = None
        self.vm_topology: Topology | None = None
        self.namespace_nodes: list[Node] = []
        self.holders: dict[str, tuple[int, str]] = {}
        # Reuse the hybrid's packet transport, not its host-facing namespace setup.
        self.transport = HybridBackend()
        self.http_servers: list[tuple[_IdentityServer, Thread]] = []
        self.helper_launchers = []

    def validate(self, topology: Topology) -> None:
        # VMBackend.create/plan validate their already-selected VM subset again.
        if self.vm_topology is topology:
            return super().validate(topology)
        if self.phase != "new":
            raise VMError("vm.already_created")
        by_id = {node.id: node for node in topology.nodes}
        if not self.vm_nodes <= by_id.keys() or any(
            by_id[name].node_class != NodeClass.L1 for name in self.vm_nodes
        ):
            raise VMError("vm.mixed_unsupported")
        if any(node.node_class == NodeClass.L2 for node in topology.nodes):
            raise VMError("vm.mixed_unsupported")
        l0 = [node for node in topology.nodes if node.node_class == NodeClass.L0]
        namespaces = [node for node in topology.nodes if (
            node.node_class == NodeClass.L1 and node.id not in self.vm_nodes
        )]
        if len(l0) > MAX_L0 or len(namespaces) > MAX_NAMESPACES:
            raise VMError("vm.mixed_unsupported")
        for node in l0:
            if len(node.interfaces) != 1 or node.services:
                raise VMError("vm.mixed_unsupported")
        for node in namespaces:
            if not 1 <= len(node.interfaces) <= 4:
                raise VMError("vm.interface_limit")
            if any(len(interface.id) > 15 or interface.id == "lo" for interface in node.interfaces):
                raise VMError("vm.mixed_unsupported")
            if node.resources is not None:
                raise VMError("vm.use_addon_limits")
            if len(node.services) > 4:
                raise VMError("vm.service_limit")
            if any(s.implementation != "static_http" or s.protocol != "tcp" for s in node.services):
                raise VMError("vm.service_unsupported")
        selected = subset(topology, [n for n in topology.nodes if n.id in self.vm_nodes])
        super().validate(selected)
        # Also detect generated-name collisions before touching the filesystem.
        MixedLab(topology, self.runner, vm_nodes=self.vm_nodes, mode=self.mode)
        self.full_topology, self.vm_topology = topology, selected
        self.namespace_nodes = namespaces
        self.transport._l0_topology = subset(topology, l0)
        self.transport.synthetic.validate(self.transport._l0_topology)

    def _make_lab(self, topology: Topology) -> Lab:
        assert self.full_topology is not None
        return MixedLab(self.full_topology, self.runner, vm_nodes=self.vm_nodes, mode=self.mode)

    def _seed_topology(self, topology: Topology) -> Topology:
        assert self.full_topology is not None
        return self.full_topology

    def plan(self, topology: Topology) -> dict:
        self.validate(topology)
        assert self.vm_topology is not None
        report = super().plan(self.vm_topology)
        report["vm_nodes"] = sorted(self.vm_nodes)
        report["namespace_nodes"] = [n.id for n in self.namespace_nodes]
        report["l0_nodes"] = [n.id for n in topology.nodes if n.node_class == NodeClass.L0]
        report["integration_verified"] = False
        return report

    def create(self, topology: Topology) -> set[str]:
        self.validate(topology)
        assert self.vm_topology is not None
        super().create(self.vm_topology)
        try:
            assert isinstance(self.lab, MixedLab)
            assert self.transport._l0_topology is not None
            self.transport.synthetic.create(self.transport._l0_topology)
            for network, name in self.lab.l0_taps.items():
                descriptor = self._export_fd(["tap", name])
                try:
                    wake_read, wake_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
                except BaseException:
                    os.close(descriptor)
                    raise
                self.transport.taps[network] = TapPort(name, descriptor, wake_read, wake_write)
                self.transport.tap_names[network] = name
            for node in self.namespace_nodes:
                self._create_namespace(node)
            self.lab.verify_isolated()
            return self.resources()
        except BaseException:
            self.destroy()
            raise

    def _export_fd(self, operation: list[str], *, node_id: str | None = None) -> int:
        assert self.socket_dir is not None and self.lab is not None
        path = self.socket_dir / "mixed-fd.sock"
        token = secrets.token_hex(32)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)
            listener.settimeout(HELPER_TIMEOUT)
            process = None
            try:
                command = addon_command("mixed-helper", "export", str(path), token, *operation)
                if node_id is not None:
                    command = self._namespace_command(node_id, command)
                process = self.runner.start(
                    self.lab.wrap(command, as_owner=True, harden=True),
                    privileged=self.lab.privileged,
                )
                with listener.accept()[0] as connection:
                    connection.settimeout(HELPER_TIMEOUT)
                    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _, uid, _ = struct.unpack("3i", credentials)
                    message, descriptors, flags, _ = socket.recv_fds(
                        connection, 128, 4, socket.MSG_CMSG_CLOEXEC,
                    )
                    try:
                        if (uid != os.getuid() or message != token.encode() or
                                len(descriptors) != 1 or flags & socket.MSG_CTRUNC):
                            raise VMError("vm.mixed_start_failed")
                        process.wait(timeout=HELPER_TIMEOUT)
                        if process.returncode:
                            raise VMError("vm.mixed_start_failed")
                        os.set_inheritable(descriptors[0], False)
                        return descriptors.pop()
                    finally:
                        for descriptor in descriptors:
                            os.close(descriptor)
            finally:
                if process is not None and process.poll() is None:
                    stop_process_group(process, grace=1)
                path.unlink(missing_ok=True)

    def _namespace_command(self, node_id: str, command: list[str]) -> list[str]:
        identity = self.holders[node_id]
        if not alive(identity):
            raise VMError("vm.mixed_start_failed")
        return [
            "nsenter", "--target", str(identity[0]), "--user", "--net",
            "--preserve-credentials", "--", *command,
        ]

    def namespace_run(self, node_id: str, command: list[str], *, check=True, timeout=10):
        """Bounded lab-owner command inside an explicitly unselected L1 node."""
        if self.lab is None:
            raise VMError("vm.not_created")
        return self.lab.run(
            self._namespace_command(node_id, command), as_owner=True, check=check, timeout=timeout,
        )

    def _create_namespace(self, node: Node) -> None:
        assert isinstance(self.lab, MixedLab)
        pidfile = self.directory / f"{node.id}.pid"
        go, ready = (self.directory / f"{node.id}-{suffix}" for suffix in ("go", "ready"))
        self.pidfiles[node.id] = pidfile
        self.auxiliary_files.update((go, ready))
        self._journal()  # Names are owned before any helper can write them.
        # No output-drainer thread or log-file creation can race rollback.
        process = self.runner.start(
            self.lab.wrap(
                addon_command("mixed-helper", "holder", str(pidfile), str(go), str(ready)),
                as_owner=True, harden=True,
            ),
            privileged=self.lab.privileged,
        )
        self.helper_launchers.append(process)
        deadline = time.monotonic() + HELPER_TIMEOUT
        pid = None
        while pid is None:
            if process.poll() is not None or time.monotonic() > deadline:
                raise VMError("vm.mixed_start_failed")
            with contextlib.suppress(FileNotFoundError, ValueError):
                pid = int(pidfile.read_text())
            time.sleep(0.02)
        start = process_start(pid)
        if start is None:
            raise VMError("vm.mixed_start_failed")
        identity = (pid, start)
        self.holders[node.id] = identity
        self.auxiliary_processes[node.id] = identity
        self._journal()  # BEFORE unshare: recovery owns the process across exec.
        go.touch(exist_ok=False)
        while not ready.exists():
            if not alive(identity) or time.monotonic() > deadline:
                raise VMError("vm.mixed_start_failed")
            time.sleep(0.02)
        namespace = file_identity(Path(f"/proc/{pid}/ns/net"))
        if not namespace or namespace == self.lab.namespace_identity:
            raise VMError("vm.state_invalid")
        self.child_namespaces.append({"holder": list(identity), "namespace_identity": namespace})
        self._journal()  # BEFORE moving links or launching anything inside the child.
        self.namespace_run(node.id, ["ip", "link", "set", "lo", "up"])
        networks = {network.id: network.ipv4_subnet for network in self.full_topology.networks}
        for interface in node.interfaces:
            local, peer = self.lab.veths[(node.id, interface.id)]
            self.lab.run(["ip", "link", "add", local, "type", "veth", "peer", "name", peer])
            self.lab.run([
                "ip", "link", "set", local, "master", self.lab.names.bridges[interface.network],
            ])
            self.lab.run(["ip", "link", "set", local, "up"])
            self.lab.run(["ip", "link", "set", peer, "netns", str(pid)])
            for command in (
                ["ip", "link", "set", peer, "name", interface.id],
                ["ip", "link", "set", interface.id, "address", interface.mac],
                ["ip", "addr", "add", f"{interface.ipv4}/{networks[interface.network].prefixlen}",
                 "dev", interface.id],
                ["ip", "link", "set", interface.id, "up"],
            ):
                self.namespace_run(node.id, command)

    def _start_http(self, node: Node) -> None:
        for service in node.services:
            descriptor = self._export_fd(
                ["http", str(node.interfaces[0].ipv4), str(service.port)], node_id=node.id,
            )
            exported = socket.socket(fileno=descriptor)
            try:
                server = _IdentityServer(
                    exported.getsockname(), _IdentityHandler, bind_and_activate=False,
                )
                server.socket.close()
                server.socket = exported
                server.identity = f"POLMON {node.id} {node.uuid}\n".encode()
                thread = Thread(
                    target=lambda s=server: s.serve_forever(poll_interval=0.1),
                    name=f"polmon-mixed-http-{node.id}", daemon=True,
                )
                thread.start()
                self.http_servers.append((server, thread))
            except BaseException:
                exported.close()
                raise

    def start(self) -> None:
        if self.phase != "created":
            raise VMError("vm.not_created")
        try:
            self.transport.synthetic.start()
            for network, tap in self.transport.taps.items():
                responder = TapResponder(
                    tap, lambda net=network: self.transport._l0_addresses(net),
                    on_frame=self.transport.capture.append,
                )
                self.transport.responders[network] = responder
                responder.start()
            for node in self.namespace_nodes:
                self._start_http(node)
            super().start()
        except BaseException:
            self.stop()
            raise

    def _node(self, node_id: str) -> Node:
        assert self.full_topology is not None
        return next(node for node in self.full_topology.nodes if node.id == node_id)

    def _additional_ready(self) -> None:
        # VMBackend calls this BEFORE publishing ready=True to the journal.
        for node in self.namespace_nodes:
            if not alive(self.holders[node.id]) or not self._node_ready(node):
                raise VMError("vm.mixed_start_failed")

    def ping_l1(self, *args, **kwargs) -> bool:
        return self.transport.ping_l1(*args, **kwargs)

    def resources(self) -> set[str]:
        return super().resources() | set(self.transport.synthetic.inspect().resources)

    def stop(self) -> None:
        for responder in self.transport.responders.values():
            responder.stop()
        self.transport.responders.clear()
        for server, thread in self.http_servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.http_servers.clear()
        self.transport.synthetic.stop()
        try:
            super().stop()
        finally:
            for process in self.helper_launchers:
                stop_process_group(process, grace=1)
            self.helper_launchers.clear()

    def destroy(self) -> None:
        self.stop()
        for tap in self.transport.taps.values():
            tap.close()
        self.transport.taps.clear()
        self.transport.tap_names.clear()
        self.transport.synthetic.destroy()
        super().destroy()

    def sample(self) -> dict:
        report = super().sample()
        report["mixed"] = {
            "vm_nodes": sorted(self.vm_nodes),
            "namespace_pids": {node: pid for node, (pid, _) in self.holders.items()},
            "l0": self.transport.synthetic.inspect().details,
            "answered_for_l0": {
                network: dict(responder.answered)
                for network, responder in self.transport.responders.items()
            },
        }
        return report


def _exclusive_text(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)


def helper_main(arguments: list[str]) -> int:
    """Private frozen/source CLI dispatch. Never called in the parent process."""
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest="action", required=True)
    holder = actions.add_parser("holder")
    for name in ("pidfile", "go", "ready"):
        holder.add_argument(name, type=Path)
    active = actions.add_parser("active")
    active.add_argument("ready", type=Path)
    export = actions.add_parser("export")
    export.add_argument("socket")
    export.add_argument("token")
    export.add_argument("kind", choices=("tap", "http"))
    export.add_argument("value")
    export.add_argument("port", nargs="?", type=int)
    args = parser.parse_args(arguments)
    if args.action == "holder":
        _exclusive_text(args.pidfile, str(os.getpid()))
        deadline = time.monotonic() + HELPER_TIMEOUT
        while not args.go.exists():
            if time.monotonic() > deadline:
                return 2
            time.sleep(0.02)
        # exec preserves the journaled PID/start identity. No child netns exists
        # before the parent's go-file acknowledges that identity's persistence.
        command = [
            "unshare", "--user", "--map-root-user", "--net",
            *addon_command("mixed-helper", "active", str(args.ready)),
        ]
        os.execvp(command[0], command)
    if args.action == "active":
        _exclusive_text(args.ready, json.dumps(file_identity(Path("/proc/self/ns/net"))))
        time.sleep(HOLDER_SECONDS)
        return 0
    with contextlib.ExitStack() as stack:
        if args.kind == "tap":
            tap = TapPort.attach(args.value)
            stack.callback(tap.close)
            descriptor = tap.file_descriptor
        else:
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            listener.bind((args.value, args.port))
            listener.listen(16)
            descriptor = listener.fileno()
        channel = stack.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
        channel.settimeout(HELPER_TIMEOUT)
        channel.connect(args.socket)
        socket.send_fds(channel, [args.token.encode()], [descriptor])
    return 0
