"""Deterministic Linux namespace, veth, bridge, and built-in service lifecycle."""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner
from polmon.orchestration.base import BackendInspection
from polmon.topology.models import NodeClass, Topology

# Run by path in an isolated interpreter: no cwd, environment, or site-packages inside the lab.
STATIC_HTTP_SCRIPT = Path(__file__).resolve().with_name("static_http.py")
_TRANSMITTED = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
_RTT = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")


def parse_ping_summary(output: str) -> dict[str, float | int | None]:
    """Parse the iputils ``ping`` summary lines; RTT fields are None when nothing returned."""
    counts = _TRANSMITTED.search(output)
    if counts is None:
        raise ValueError("ping output has no packet summary")
    transmitted, received = int(counts.group(1)), int(counts.group(2))
    rtt = _RTT.search(output)
    values = [float(item) for item in rtt.groups()] if rtt else [None, None, None, None]
    return {
        "transmitted": transmitted,
        "received": received,
        "loss_percent": ((transmitted - received) / transmitted) * 100 if transmitted else 0.0,
        "rtt_min_ms": values[0],
        "rtt_avg_ms": values[1],
        "rtt_max_ms": values[2],
        "rtt_mdev_ms": values[3],
    }


@dataclass(frozen=True, slots=True)
class NamespaceNames:
    namespaces: dict[str, str]
    bridges: dict[str, str]
    host_veths: dict[tuple[str, str], str]
    peer_veths: dict[tuple[str, str], str]


class NamespaceBackend:
    name = "namespace"

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        python_executable: str | None = None,
        require_linux: bool = True,
        owner_uid: int | None = None,
        owner_gid: int | None = None,
        run_directory: str | Path | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.python_executable = str(Path(python_executable or sys.executable).resolve())
        self.require_linux = require_linux
        self.owner_uid = owner_uid if owner_uid is not None else self._process_id("getuid")
        self.owner_gid = owner_gid if owner_gid is not None else self._process_id("getgid")
        self.owner_name = (
            importlib.import_module("pwd").getpwuid(self.owner_uid).pw_name
            if sys.platform != "win32"
            else ""
        )
        self.run_directory = Path(run_directory) if run_directory else None
        self.topology: Topology | None = None
        self.names: NamespaceNames | None = None
        self.created_namespaces: set[str] = set()
        self.created_bridges: set[str] = set()
        self.created_veths: set[str] = set()
        self.services: dict[tuple[str, str], subprocess.Popen[bytes]] = {}
        self.vnc_processes: dict[
            str, tuple[subprocess.Popen[bytes], subprocess.Popen[bytes], subprocess.Popen[bytes]]
        ] = {}
        self.running = False

    @staticmethod
    def _process_id(attribute: str) -> int:
        getter = getattr(os, attribute, None)
        return int(getter()) if getter is not None else 0

    @staticmethod
    def _name(prefix: str, value: str, suffix: str = "") -> str:
        digest = hashlib.blake2s(value.encode("utf-8"), digest_size=4).hexdigest()
        name = f"{prefix}{digest}{suffix}"
        if len(name) > 15 or not name.startswith(("polmon", "veth")):
            raise ValueError("generated laboratory interface name is unsafe")
        return name

    def _names(self, topology: Topology) -> NamespaceNames:
        namespaces = {
            node.id: self._name("polmon", f"{topology.id}:{node.id}", "n")
            for node in topology.nodes
        }
        bridges = {
            network.id: self._name("polmon", f"{topology.id}:{network.id}", "b")
            for network in topology.networks
        }
        host_veths: dict[tuple[str, str], str] = {}
        peer_veths: dict[tuple[str, str], str] = {}
        for node in topology.nodes:
            for interface in node.interfaces:
                key = (node.id, interface.id)
                seed = f"{topology.id}:{node.id}:{interface.id}"
                host_veths[key] = self._name("veth", seed, "h")
                peer_veths[key] = self._name("veth", seed, "p")
        return NamespaceNames(namespaces, bridges, host_veths, peer_veths)

    def validate(self, topology: Topology) -> None:
        if self.require_linux and not sys.platform.startswith("linux"):
            raise ValueError("namespace backend requires Linux")
        unsupported = [node.id for node in topology.nodes if node.node_class is not NodeClass.L1]
        if unsupported:
            raise ValueError(f"namespace backend cannot create non-L1 nodes: {unsupported}")
        if any(not node.interfaces for node in topology.nodes):
            raise ValueError("every L1 node requires at least one interface")
        for node in topology.nodes:
            for service in node.services:
                if service.implementation not in {"static_http", "ssh"}:
                    raise ValueError(f"unsupported built-in service '{service.implementation}'")
                if service.protocol != "tcp":
                    raise ValueError("built-in namespace services are TCP only")
                if service.implementation == "ssh" and shutil.which("sshd") is None:
                    raise ValueError("console.sshd_missing")
        if not Path(self.python_executable).is_file():
            raise ValueError("configured Python executable does not exist")
        self.names = self._names(topology)

    def create(self, topology: Topology) -> set[str]:
        """Create bridges, namespaces, and veths with one privileged batch per namespace.

        Every generated name is recorded as owned *before* the batch runs, so a failure at any
        line is rolled back by ``destroy()`` without knowing how far the batch got.
        """
        self.topology = topology
        self.names = self.names or self._names(topology)
        existing = self._preexisting(self.names)
        if existing:
            # Never adopt objects this backend did not create: rollback would delete them.
            raise RuntimeError(
                "laboratory objects with this topology's generated names already exist "
                f"({', '.join(existing)}); another deployment of the same topology is running or "
                "a previous run left them behind (inspect with scripts/lab-cleanup.sh)"
            )
        prefixes = {network.id: network.ipv4_subnet.prefixlen for network in topology.networks}
        host_lines: list[str] = []
        namespace_lines: dict[str, list[str]] = {}
        resources: set[str] = set()
        for network in topology.networks:
            bridge = self.names.bridges[network.id]
            host_lines += [f"link add name {bridge} type bridge", f"link set dev {bridge} up"]
            self.created_bridges.add(bridge)
            resources.add(f"bridge:{bridge}")
        for node in topology.nodes:
            namespace = self.names.namespaces[node.id]
            host_lines.append(f"netns add {namespace}")
            self.created_namespaces.add(namespace)
            resources.add(f"netns:{namespace}")
            inside_lines = ["link set lo up"]
            for index, interface in enumerate(node.interfaces):
                key = (node.id, interface.id)
                host = self.names.host_veths[key]
                peer = self.names.peer_veths[key]
                inside = f"eth{index}"
                bridge = self.names.bridges[interface.network]
                host_lines += [
                    f"link add {host} type veth peer name {peer}",
                    f"link set {host} master {bridge}",
                    f"link set dev {host} up",
                    f"link set {peer} netns {namespace}",
                ]
                self.created_veths.add(host)
                resources.add(f"link:{host}")
                address = f"{interface.ipv4}/{prefixes[interface.network]}"
                inside_lines += [
                    f"link set {peer} name {inside}",
                    f"link set dev {inside} address {interface.mac}",
                    f"address add {address} dev {inside}",
                    f"link set dev {inside} up",
                ]
            namespace_lines[namespace] = inside_lines
        try:
            self._ip_batch(host_lines)
            for namespace, lines in namespace_lines.items():
                self._ip_batch(lines, namespace=namespace)
        except Exception:
            self.destroy()
            raise
        return resources

    def _preexisting(self, names: NamespaceNames) -> list[str]:
        """Generated names the kernel already reports (rootless ``ip`` queries)."""
        links = self.runner.run(["ip", "-o", "link", "show"], check=False).stdout
        namespaces = self.runner.run(["ip", "netns", "list"], check=False).stdout
        link_names = {
            line.split(": ")[1].split("@")[0] for line in links.splitlines() if ": " in line
        }
        namespace_names = {line.split()[0] for line in namespaces.splitlines() if line.strip()}
        planned_links = [
            *names.bridges.values(),
            *names.host_veths.values(),
            *names.peer_veths.values(),
        ]
        return sorted(
            [name for name in planned_links if name in link_names]
            + [name for name in names.namespaces.values() if name in namespace_names]
        )

    def start(self) -> None:
        if self.topology is None or self.names is None:
            raise RuntimeError("namespace topology has not been created")
        for node in self.topology.nodes:
            for service in node.services:
                if service.implementation == "ssh":
                    self._start_ssh(node.id, service.id, service.port, str(node.interfaces[0].ipv4))
                else:
                    self._start_service(
                        node.id, service.id, service.port, str(node.interfaces[0].ipv4)
                    )
        self.running = True

    def stop(self) -> None:
        for processes in list(self.vnc_processes.values()):
            for process in processes:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=3)
                    except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
                        pass
        self.vnc_processes.clear()
        for process in list(self.services.values()):
            poll = process.poll()
            if poll is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
                    pass
        self.services.clear()
        self.running = False

    def start_vnc(self, node_id: str) -> dict[str, object]:
        if self.run_directory is None:
            raise RuntimeError("console.vnc_unavailable")
        if self.topology is None:
            raise RuntimeError("topology is unavailable")
        node = next((item for item in self.topology.nodes if item.id == node_id), None)
        if node is None or node.node_class is not NodeClass.L1:
            raise ValueError("console.l1_required")
        address, port = self.vnc_service(node_id)
        directory = self.run_directory / "vnc" / node_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        display = f":{100 + (int(secrets.token_hex(2), 16) % 800)}"
        display_number = display[1:]
        log = directory / "vnc.log"
        stream = log.open("ab")
        namespace = self._namespace(node_id)
        xvfb = self.runner.start(
            self._as_owner(
                namespace,
                "Xvfb",
                display,
                "-screen",
                "0",
                "1024x768x24",
                "-nolisten",
                "tcp",
            ),
            privileged=True,
        )
        xclock = self.runner.start(
            self._as_owner(namespace, "env", f"DISPLAY={display}", "xclock", "-digital"),
            privileged=True,
        )
        x11vnc = self.runner.start(
            self._as_owner(
                namespace, "env", f"DISPLAY={display}", "x11vnc", "-display", display,
                "-rfbport", str(port), "-listen", address, "-forever", "-shared",
                "-nopw", "-o", str(log),
            ),
            privileged=True,
        )
        stream.close()
        self.vnc_processes[node_id] = (xvfb, xclock, x11vnc)
        return {
            "node_id": node_id,
            "address": address,
            "port": port,
            "display": display,
            "display_number": display_number,
        }

    def vnc_service(self, node_id: str) -> tuple[str, int]:
        if self.topology is None:
            raise ValueError("topology is unavailable")
        node = next((item for item in self.topology.nodes if item.id == node_id), None)
        if node is None:
            raise ValueError("console.node_unknown")
        address = str(node.interfaces[0].ipv4)
        return address, 5900 + node.interfaces[0].ipv4.packed[-1]

    def vnc_proxy_argv(self, node_id: str) -> list[str]:
        address, port = self.vnc_service(node_id)
        namespace = self._namespace(node_id)
        proxy = "\n".join(
            (
                "import selectors, socket, sys, time",
                "s = None",
                "for _ in range(50):",
                "    try:",
                "        s = socket.create_connection((sys.argv[1], int(sys.argv[2])), .2)",
                "        break",
                "    except OSError:",
                "        time.sleep(.1)",
                "if s is None:",
                "    raise SystemExit(1)",
                "q = selectors.DefaultSelector()",
                "q.register(s, selectors.EVENT_READ)",
                "q.register(sys.stdin.buffer, selectors.EVENT_READ)",
                "while True:",
                "    for key, _ in q.select():",
                "        data = key.fileobj.recv(65536) if key.fileobj is s else key.fileobj.read(65536)",
                "        if not data:",
                "            raise SystemExit",
                "        destination = sys.stdout.buffer if key.fileobj is s else s",
                "        destination.write(data)",
                "        destination.flush()",
            )
        )
        return [
            "ip", "netns", "exec", namespace, sys.executable, "-u", "-c", proxy, address, str(port)
        ]

    def destroy(self) -> None:
        self.stop()
        # Namespaces first (removes moved veth peers and their host ends), then any host veth
        # that never reached its namespace, then bridges. -force continues past already-gone
        # objects, so one privileged call tears down everything this backend owns.
        lines = [f"netns del {namespace}" for namespace in sorted(self.created_namespaces)]
        lines += [f"link del dev {veth}" for veth in sorted(self.created_veths)]
        lines += [f"link del dev {bridge}" for bridge in sorted(self.created_bridges)]
        if lines:
            self._ip_batch(lines, check=False, force=True)
        self.created_namespaces.clear()
        self.created_veths.clear()
        self.created_bridges.clear()
        self.running = False

    def inspect(self) -> BackendInspection:
        resources = {
            *(f"netns:{item}" for item in self.created_namespaces),
            *(f"bridge:{item}" for item in self.created_bridges),
            *(f"link:{item}" for item in self.created_veths),
        }
        return BackendInspection(
            backend=self.name,
            resources=frozenset(resources),
            details={
                "running": self.running,
                "namespace_count": len(self.created_namespaces),
                "service_count": len(self.services),
                "names": asdict(self.names) if self.names else None,
            },
        )

    def _as_owner(self, namespace: str, *argv: str) -> list[str]:
        """Command running ``argv`` inside ``namespace`` as the invoking user, never as root.

        Only ``ip`` (namespace entry) and ``setpriv`` (privilege drop) execute with privileges;
        probes and services run unprivileged (``ping`` relies on its ``cap_net_raw`` file
        capability).
        """
        return [
            "ip",
            "netns",
            "exec",
            namespace,
            "setpriv",
            "--reuid",
            str(self.owner_uid),
            "--regid",
            str(self.owner_gid),
            "--clear-groups",
            *argv,
        ]

    def ping(self, source_node: str, destination: str) -> bool:
        namespace = self._namespace(source_node)
        result = self.runner.run(
            self._as_owner(namespace, "ping", "-c", "1", "-W", "2", destination),
            privileged=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0

    def ping_statistics(
        self, source_node: str, destination: str, *, count: int = 5, interval: float = 0.2
    ) -> dict[str, float | int | None]:
        """Send ``count`` kernel ICMP echoes inside the lab and return loss and RTT figures."""
        if not 1 <= count <= 100:
            raise ValueError("ping count must be between 1 and 100")
        if not 0.2 <= interval <= 5:  # 0.2 s is also the iputils minimum for unprivileged users
            raise ValueError("ping interval must be between 0.2 and 5 seconds")
        namespace = self._namespace(source_node)
        result = self.runner.run(
            self._as_owner(
                namespace,
                "ping",
                "-n",
                "-q",
                "-c",
                str(count),
                "-i",
                f"{interval:g}",
                "-W",
                "2",
                destination,
            ),
            privileged=True,
            check=False,
            timeout=count * interval + 10,
        )
        return parse_ping_summary(result.stdout)

    def probe_tcp(self, source_node: str, destination: str, port: int) -> bool:
        namespace = self._namespace(source_node)
        code = (
            "import socket,sys;"
            "s=socket.create_connection((sys.argv[1],int(sys.argv[2])),2);"
            "s.sendall(b'GET / HTTP/1.0\\r\\nHost: lab\\r\\n\\r\\n');"
            "data=s.recv(16);s.close();"
            "raise SystemExit(0 if data.startswith(b'HTTP/') else 1)"
        )
        result = self.runner.run(
            self._as_owner(
                namespace, self.python_executable, "-I", "-S", "-c", code, destination, str(port)
            ),
            privileged=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0

    def _start_service(self, node_id: str, service_id: str, port: int, address: str) -> None:
        namespace = self._namespace(node_id)
        command = self._as_owner(
            namespace,
            self.python_executable,
            "-I",
            "-S",
            str(STATIC_HTTP_SCRIPT),
            "--bind",
            address,
            "--port",
            str(port),
        )
        self.services[(node_id, service_id)] = self.runner.start(command, privileged=True)

    def _start_ssh(self, node_id: str, service_id: str, port: int, address: str) -> None:
        if self.run_directory is None:
            raise RuntimeError("SSH service requires a deployment run directory")
        directory = self.run_directory / "console"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        host_key = directory / "ssh_host_ed25519_key"
        client_key = directory / "id_ed25519"
        authorized = directory / "authorized_keys"
        if not host_key.exists():
            self.runner.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)])
        if not client_key.exists():
            self.runner.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(client_key)])
        authorized.write_text(
            client_key.with_suffix(".pub").read_text(encoding="utf-8"), encoding="utf-8"
        )
        for secret in (host_key, client_key, authorized):
            os.chmod(secret, 0o600)
        config = directory / f"sshd-{node_id}.conf"
        pid_file = directory / f"sshd-{node_id}.pid"
        config.write_text(
            "\n".join(
                (
                    f"Port {port}",
                    f"ListenAddress {address}",
                    f"HostKey {host_key}",
                    f"PidFile {pid_file}",
                    f"AuthorizedKeysFile {authorized}",
                    "PasswordAuthentication no",
                    "KbdInteractiveAuthentication no",
                    "PermitRootLogin no",
                    "UsePAM no",
                    "StrictModes no",
                    f"AllowUsers {self.owner_name}",
                    "LogLevel VERBOSE",
                    "PrintMotd no",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(config, 0o600)
        namespace = self._namespace(node_id)
        sshd = shutil.which("sshd")
        if sshd is None:
            raise RuntimeError("console.sshd_missing")
        command = ["ip", "netns", "exec", namespace, sshd, "-D", "-e", "-f", str(config)]
        self.services[(node_id, service_id)] = self.runner.start(command, privileged=True)

    def ssh_service(self, node_id: str) -> tuple[str, int]:
        if self.topology is None:
            raise ValueError("topology is unavailable")
        node = next((item for item in self.topology.nodes if item.id == node_id), None)
        if node is None:
            raise ValueError(f"unknown namespace node '{node_id}'")
        service = next((item for item in node.services if item.implementation == "ssh"), None)
        if service is None:
            raise ValueError("console.ssh_service_missing")
        return str(node.interfaces[0].ipv4), service.port

    def ssh_command(self, node_id: str, argv: list[str], *, timeout: float = 10):
        command = self.ssh_argv(node_id, interactive=False) + ["--", *argv]
        return self.runner.run_bounded(command, privileged=True, timeout=timeout)

    def ssh_argv(self, node_id: str, *, interactive: bool) -> list[str]:
        if self.run_directory is None:
            raise ValueError("console.ssh_unavailable")
        address, port = self.ssh_service(node_id)
        namespace = self._namespace(node_id)
        key = self.run_directory / "console" / "id_ed25519"
        command = self._as_owner(
            namespace,
            "ssh",
            *(["-tt"] if interactive else []),
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-p",
            str(port),
            f"{self.owner_name}@{address}",
        )
        return command

    def _namespace(self, node_id: str) -> str:
        if self.names is None or node_id not in self.names.namespaces:
            raise ValueError(f"unknown namespace node '{node_id}'")
        return self.names.namespaces[node_id]

    def _ip_batch(
        self,
        lines: list[str],
        *,
        namespace: str | None = None,
        check: bool = True,
        force: bool = False,
    ) -> None:
        """Run ``ip`` batch lines in one privileged call (inside ``namespace`` when given).

        Lines are generated only from validated identifiers, addresses, and generated names;
        ``ip -batch`` executes subcommands directly and never involves a shell.
        """
        command = ["ip"]
        if namespace is not None:
            command += ["-n", namespace]
        if force:
            command.append("-force")
        command += ["-batch", "-"]
        self.runner.run(
            command,
            privileged=True,
            check=check,
            timeout=10 + len(lines),
            input="".join(f"{line}\n" for line in lines),
        )
