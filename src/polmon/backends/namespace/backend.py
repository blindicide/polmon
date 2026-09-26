"""Deterministic Linux namespace, veth, bridge, and built-in service lifecycle."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner
from polmon.orchestration.base import BackendInspection
from polmon.topology.models import NodeClass, Topology


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
    ) -> None:
        self.runner = runner or CommandRunner()
        self.python_executable = str(Path(python_executable or sys.executable).resolve())
        self.require_linux = require_linux
        self.topology: Topology | None = None
        self.names: NamespaceNames | None = None
        self.created_namespaces: set[str] = set()
        self.created_bridges: set[str] = set()
        self.created_veths: set[str] = set()
        self.services: dict[tuple[str, str], subprocess.Popen[bytes]] = {}
        self.running = False

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
                if service.implementation != "static_http":
                    raise ValueError(f"unsupported built-in service '{service.implementation}'")
        if not Path(self.python_executable).is_file():
            raise ValueError("configured Python executable does not exist")
        self.names = self._names(topology)

    def create(self, topology: Topology) -> set[str]:
        self.topology = topology
        self.names = self.names or self._names(topology)
        resources: set[str] = set()
        try:
            for network in topology.networks:
                bridge = self.names.bridges[network.id]
                self._ip("link", "add", "name", bridge, "type", "bridge")
                self.created_bridges.add(bridge)
                resources.add(f"bridge:{bridge}")
                self._ip("link", "set", "dev", bridge, "up")
            prefixes = {network.id: network.ipv4_subnet.prefixlen for network in topology.networks}
            for node in topology.nodes:
                namespace = self.names.namespaces[node.id]
                self._ip("netns", "add", namespace)
                self.created_namespaces.add(namespace)
                resources.add(f"netns:{namespace}")
                self._ip("-n", namespace, "link", "set", "lo", "up")
                for index, interface in enumerate(node.interfaces):
                    key = (node.id, interface.id)
                    host = self.names.host_veths[key]
                    peer = self.names.peer_veths[key]
                    inside = f"eth{index}"
                    self._ip("link", "add", host, "type", "veth", "peer", "name", peer)
                    self.created_veths.add(host)
                    resources.add(f"link:{host}")
                    self._ip("link", "set", host, "master", self.names.bridges[interface.network])
                    self._ip("link", "set", "dev", host, "up")
                    self._ip("link", "set", peer, "netns", namespace)
                    self._ip("-n", namespace, "link", "set", peer, "name", inside)
                    self._ip(
                        "-n",
                        namespace,
                        "link",
                        "set",
                        "dev",
                        inside,
                        "address",
                        interface.mac,
                    )
                    address = f"{interface.ipv4}/{prefixes[interface.network]}"
                    self._ip("-n", namespace, "address", "add", address, "dev", inside)
                    self._ip("-n", namespace, "link", "set", "dev", inside, "up")
        except Exception:
            self.destroy()
            raise
        return resources

    def start(self) -> None:
        if self.topology is None or self.names is None:
            raise RuntimeError("namespace topology has not been created")
        for node in self.topology.nodes:
            for service in node.services:
                self._start_service(node.id, service.id, service.port, str(node.interfaces[0].ipv4))
        self.running = True

    def stop(self) -> None:
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

    def destroy(self) -> None:
        self.stop()
        for namespace in sorted(self.created_namespaces):
            self._ip("netns", "del", namespace, check=False)
        self.created_namespaces.clear()
        self.created_veths.clear()
        for bridge in sorted(self.created_bridges):
            self._ip("link", "del", "dev", bridge, check=False)
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

    def ping(self, source_node: str, destination: str) -> bool:
        namespace = self._namespace(source_node)
        result = self.runner.run(
            ["ip", "netns", "exec", namespace, "ping", "-c", "1", "-W", "2", destination],
            privileged=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0

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
            [
                "ip",
                "netns",
                "exec",
                namespace,
                self.python_executable,
                "-c",
                code,
                destination,
                str(port),
            ],
            privileged=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0

    def _start_service(self, node_id: str, service_id: str, port: int, address: str) -> None:
        namespace = self._namespace(node_id)
        command = [
            "ip",
            "netns",
            "exec",
            namespace,
            "setpriv",
            "--reuid",
            str(os.getuid()),
            "--regid",
            str(os.getgid()),
            "--clear-groups",
            self.python_executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            address,
        ]
        self.services[(node_id, service_id)] = self.runner.start(command, privileged=True)

    def _namespace(self, node_id: str) -> str:
        if self.names is None or node_id not in self.names.namespaces:
            raise ValueError(f"unknown namespace node '{node_id}'")
        return self.names.namespaces[node_id]

    def _ip(self, *arguments: str, check: bool = True) -> None:
        self.runner.run(["ip", *arguments], privileged=True, check=check)
