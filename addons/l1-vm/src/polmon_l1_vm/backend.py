"""Изолированные KVM-гости для узлов L1: жизненный цикл, ограничения, измерения."""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from pydantic import Field

from polmon.backends.namespace.journal import LabOwner
from polmon.backends.namespace.runner import CommandRunner, stop_process_group
from polmon.orchestration.base import BackendInspection, ExecutionBackend
from polmon.topology.models import Node, NodeClass, StrictModel, Topology
from polmon.version import __version__
from polmon_l1_vm import qmp
from polmon_l1_vm.host import admit, alive, process_start, terminate
from polmon_l1_vm.images import ImageManifest, OverlayStore, VMError, verify_image
from polmon_l1_vm.lab import MODES, Lab, file_identity
from polmon_l1_vm.recovery import SOCKET_PREFIX, STATE_NAME, write_state
from polmon_l1_vm.seed import create_seed

LOG_LIMIT_BYTES = 262_144


class VMLimits(StrictModel):
    max_vms: int = Field(default=2, ge=1, le=4)
    memory_mb: int = Field(default=256, ge=128, le=512)
    max_total_memory_mb: int = Field(default=768, ge=256, le=1536)
    memory_reserve_mb: int = Field(default=256, ge=256, le=4096)
    disk_reserve_mb: int = Field(default=512, ge=128, le=4096)
    max_total_disk_mb: int = Field(default=4096, ge=128, le=8192)
    boot_timeout_seconds: int = Field(default=90, ge=10, le=180)
    # Один vCPU на гостя; ни подмены на TCG, ни переподписки.
    max_vcpus: int = Field(default=2, ge=1, le=4)


def _userns_works() -> bool:
    try:
        return (
            subprocess.run(
                ["unshare", "--user", "--map-root-user", "--net", "true"],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sudo_works() -> bool:
    try:
        return (
            subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def readiness() -> dict:
    missing = []
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        missing.append("vm.linux_x86_64_required")
    for name, code in [
        ("qemu-system-x86_64", "vm.qemu_missing"),
        ("qemu-img", "vm.qemu_img_missing"),
        ("genisoimage", "vm.seed_tool_missing"),
        ("ip", "vm.ip_missing"),
    ]:
        if shutil.which(name) is None:
            missing.append(code)
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        missing.append("vm.kvm_unavailable")
    if not os.access("/dev/net/tun", os.R_OK | os.W_OK):
        missing.append("vm.tun_unavailable")
    # Режимы сети проверяются отдельно: достаточно любого одного.
    modes = {"userns": False, "netns": False}
    reasons = []
    if shutil.which("unshare") and shutil.which("nsenter"):
        modes["userns"] = _userns_works()
    if not modes["userns"]:
        reasons.append("vm.userns_unavailable")
    if shutil.which("sudo") and shutil.which("setpriv"):
        modes["netns"] = _sudo_works()
    if not modes["netns"]:
        reasons.append("vm.sudo_unavailable")
    if not any(modes.values()):
        missing.extend(reasons)
    return {
        "version": __version__,
        "backend": "l1-vm-addon",
        "ready": not missing,
        "runtime_implemented": True,
        "modes": modes,
        "missing": missing,
        "fidelity": "full Linux VM; namespace L1 remains unchanged",
        "integration_verified": False,
    }


class VMBackend(ExecutionBackend):
    """Гости QEMU/KVM в отдельной лабораторной сети; владеет только созданными им ресурсами."""

    name = "l1-vm-addon"

    def __init__(
        self,
        *,
        base: Path,
        manifest: ImageManifest,
        directory: Path,
        limits: VMLimits | None = None,
        runner: CommandRunner | None = None,
        mode: str = "userns",
        peer_report: bool = False,
    ):
        self.base, self.manifest = base.resolve(), manifest
        self.directory = directory.resolve()
        if any(c in str(path) for path in (self.base, self.directory) for c in ",\n\r"):
            raise VMError("vm.path_invalid")
        if mode not in MODES:
            raise VMError("vm.mode_invalid")
        self.limits = limits or VMLimits()
        self.runner = runner or CommandRunner()
        self.mode = mode
        self.peer_report = peer_report
        self.topology: Topology | None = None
        self.lab: Lab | None = None
        self.overlays: OverlayStore | None = None
        self.seeds: list[Path] = []
        self.socket_dir: Path | None = None
        self.launchers: dict[str, subprocess.Popen[bytes]] = {}
        self.identities: dict[str, tuple[int, str]] = {}
        self.pidfiles: dict[str, Path] = {}
        self.owner = LabOwner.current()
        self.socket_identity = None
        self.phase = "new"
        self.image_info: dict = {}
        self.admission: dict = {}
        self.started_at: float | None = None

    def validate(self, topology: Topology) -> None:
        if not 1 <= len(topology.nodes) <= self.limits.max_vms:
            raise VMError("vm.node_limit")
        if not 1 <= len(topology.networks) <= 4:
            raise VMError("vm.network_limit")
        for node in topology.nodes:
            if node.node_class != NodeClass.L1:
                raise VMError("vm.l1_only")
            if not 1 <= len(node.interfaces) <= 4:
                raise VMError("vm.interface_limit")
            if node.resources is not None:
                # Бюджет ВМ задаётся в VMLimits, оценки пространств имён не переосмысливаются.
                raise VMError("vm.use_addon_limits")
            if any(s.implementation != "static_http" or s.protocol != "tcp" for s in node.services):
                raise VMError("vm.service_unsupported")
            if len(node.services) > 4:
                raise VMError("vm.service_limit")
        if len(topology.nodes) > self.limits.max_vcpus:
            raise VMError("vm.cpu_limit")
        requested = len(topology.nodes) * (self.limits.memory_mb + 64)
        if requested > self.limits.max_total_memory_mb:
            raise VMError("vm.memory_limit")
        if len(topology.nodes) > (os.cpu_count() or 1):
            raise VMError("vm.host_cpu_limit")

    def plan(self, topology: Topology) -> dict:
        self.validate(topology)
        return {
            "runtime_implemented": True,
            "estimated_memory_mb": len(topology.nodes) * (self.limits.memory_mb + 64),
            "host_memory_reserve_mb": self.limits.memory_reserve_mb,
            "storage": "reviewed read-only base; exclusive per-node QCOW2 overlays",
            "network": "TAPs/bridges inside a dedicated lab namespace; no host uplink or NAT",
            "nodes": [
                {
                    "id": node.id,
                    "uuid": str(node.uuid),
                    "overlay": f"{node.id}.qcow2",
                    "interfaces": [
                        interface.model_dump(mode="json") for interface in node.interfaces
                    ],
                }
                for node in topology.nodes
            ],
            "modes": list(MODES),
        }

    # -- жизненный цикл -------------------------------------------------------------------

    def _journal(self) -> None:
        # Journal intended filenames before creation; the run directory was admitted empty.
        files = sorted(
            name
            for node in (self.topology.nodes if self.topology else [])
            for name in (f"{node.id}.qcow2", f"{node.id}-seed.iso", f"{node.id}-qemu.log")
        )
        write_state(
            self.directory,
            {
                "owner": asdict(self.owner),
                "socket_identity": self.socket_identity,
                "mode": self.mode,
                "topology": self.topology.id if self.topology else None,
                **(self.lab.state() if self.lab else {}),
                "files": files,
                "pidfiles": sorted(path.name for path in self.pidfiles.values()),
                "socket_dir": str(self.socket_dir) if self.socket_dir else None,
                "processes": {node: list(identity) for node, identity in self.identities.items()},
            },
        )

    def create(self, topology: Topology) -> set[str]:
        self.validate(topology)
        if self.phase != "new":
            raise VMError("vm.already_created")
        if self.directory.exists() and (
            not self.directory.is_dir() or any(self.directory.iterdir())
        ):
            raise VMError("vm.directory_not_empty")
        self.image_info = verify_image(self.base, self.manifest, self.runner)
        self.admission = admit(
            count=len(topology.nodes),
            memory_mb=self.limits.memory_mb,
            memory_reserve_mb=self.limits.memory_reserve_mb,
            directory=self.directory,
            disk_reserve_mb=self.limits.disk_reserve_mb,
            max_total_disk_mb=self.limits.max_total_disk_mb,
            virtual_bytes=self.image_info["virtual_bytes"],
        )
        self.topology = topology
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive reservation prevents two backends adopting the same empty directory.
        descriptor = os.open(
            self.directory / STATE_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        os.close(descriptor)
        self.phase = "creating"
        self.overlays = OverlayStore(self.directory, self.base, self.runner)
        try:
            # Короткий каталог: путь UNIX-сокета QMP не должен превышать 108 байт.
            self.socket_dir = Path(tempfile.mkdtemp(prefix=SOCKET_PREFIX)).resolve()
            self.socket_identity = file_identity(self.socket_dir)
            self._journal()
            self.lab = Lab(topology, self.runner, mode=self.mode)
            self.lab.on_created = self._journal
            self.lab.create()
            self._journal()
            for node in topology.nodes:
                self.overlays.create(node.id)
                self._journal()
                self.seeds.append(
                    create_seed(
                        self.directory, node, topology, self.runner, peer_report=self.peer_report
                    )
                )
                self._journal()
        except BaseException:
            self.destroy()
            raise
        self.phase = "created"
        return self.resources()

    def resources(self) -> set[str]:
        found: set[str] = set()
        if self.lab is not None:
            found |= set(self.lab.resources())
        if self.overlays is not None:
            found |= {f"file:{path}" for path in self.overlays.owned if path.exists()}
        found |= {f"file:{path}" for path in self.seeds if path.exists()}
        found |= {
            f"qemu:{pid}:{start}" for pid, start in self.identities.values() if alive((pid, start))
        }
        if self.socket_dir is not None and self.socket_dir.exists():
            found.add(f"dir:{self.socket_dir}")
        return found

    def _command(self, node: Node, overlay: Path, seed: Path) -> list[str]:
        assert self.lab is not None and self.socket_dir is not None
        argv = [
            "qemu-system-x86_64",
            "-name",
            node.id,
            "-uuid",
            str(node.uuid),
            # Только KVM: без него гость не запускается, подмены на TCG нет.
            "-machine",
            "pc,accel=kvm",
            "-cpu",
            "host",
            "-m",
            str(self.limits.memory_mb),
            "-smp",
            "1",
            "-nodefaults",
            "-no-user-config",
            "-display",
            "none",
            "-no-reboot",
            "-chardev",
            "stdio,id=serial0,signal=off",
            "-serial",
            "chardev:serial0",
            "-drive",
            f"file={overlay},if=virtio,format=qcow2",
            "-drive",
            f"file={seed},if=virtio,format=raw,readonly=on",
            "-qmp",
            f"unix:{self.socket_dir / (node.id + '.qmp')},server=on,wait=off",
            "-pidfile",
            str(self.pidfiles[node.id]),
            # Фильтр системных вызовов QEMU: без запуска процессов и повышения привилегий.
            "-sandbox",
            "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
        ]
        for index, interface in enumerate(node.interfaces):
            tap = self.lab.names.taps[(node.id, interface.id)]
            argv += [
                "-netdev",
                f"tap,id=net{index},ifname={tap},script=no,downscript=no",
                "-device",
                f"virtio-net-pci,netdev=net{index},mac={interface.mac}",
            ]
        return argv

    def start(self) -> None:
        if self.phase != "created" or self.topology is None or self.lab is None:
            raise VMError("vm.not_created")
        assert self.overlays is not None
        self.phase = "starting"
        try:
            for node, seed in zip(self.topology.nodes, self.seeds, strict=True):
                self.pidfiles[node.id] = self.directory / f"{node.id}.pid"
                self._journal()
                overlay = self.directory / f"{node.id}.qcow2"
                self.launchers[node.id] = self.lab.start(
                    self._command(node, overlay, seed),
                    log_path=self.directory / f"{node.id}-qemu.log",
                    max_output_bytes=LOG_LIMIT_BYTES,
                )
                self._await_process(node.id)
                self._journal()
        except BaseException:
            self.stop()
            self.phase = "created"
            raise
        self.started_at = time.monotonic()
        self.phase = "started"

    def _await_process(self, node_id: str) -> None:
        """Ждёт pid-файл и сокет QMP; сразу отказывает, если QEMU завершился."""
        assert self.socket_dir is not None
        launcher, pidfile = self.launchers[node_id], self.pidfiles[node_id]
        socket_path = self.socket_dir / f"{node_id}.qmp"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if launcher.poll() is not None:
                raise VMError("vm.qemu_exited")
            if pidfile.exists() and socket_path.exists():
                try:
                    pid = int(pidfile.read_text().strip())
                except ValueError:
                    pid = 0
                start = process_start(pid) if pid else None
                if start is not None:
                    self.identities[node_id] = (pid, start)
                    return
            time.sleep(0.05)
        raise VMError("vm.qemu_start_timeout")

    @property
    def qemu_pids(self) -> list[int]:
        return [pid for pid, start in self.identities.values() if alive((pid, start))]

    def stop(self) -> None:
        for node_id, identity in list(self.identities.items()):
            if alive(identity) and self.socket_dir is not None:
                with contextlib.suppress(VMError):
                    qmp.command(str(self.socket_dir / f"{node_id}.qmp"), "quit", timeout=2)
            if not terminate(identity, grace=3) and alive(identity):
                raise VMError("vm.cleanup_failed")
        for launcher in self.launchers.values():
            if launcher.poll() is None:
                stop_process_group(launcher, grace=1)
        self.launchers.clear()
        if self.phase in ("started", "starting"):
            self.phase = "stopped"

    def destroy(self) -> None:
        """Идемпотентно: процессы, пространство, диски, образы начальной конфигурации, сокеты."""
        if self.phase == "new":
            return
        if self.socket_dir is not None and (
            self.socket_dir.is_symlink()
            or (self.socket_dir.exists() and file_identity(self.socket_dir) != self.socket_identity)
        ):
            raise VMError("vm.state_invalid")
        self.stop()
        if self.lab is not None:
            self.lab.destroy()
        if self.overlays is not None:
            self.overlays.destroy()
        for path in self.seeds:
            path.unlink(missing_ok=True)
        self.seeds.clear()
        for path in self.pidfiles.values():
            path.unlink(missing_ok=True)
        self.pidfiles.clear()
        # Журналы QEMU принадлежат запуску; оставленные, они мешают повторному созданию.
        for node in self.topology.nodes if self.topology else []:
            (self.directory / f"{node.id}-qemu.log").unlink(missing_ok=True)
        self.identities.clear()
        if self.socket_dir is not None:
            if self.socket_dir.exists():
                shutil.rmtree(self.socket_dir)
            self.socket_dir = None
        (self.directory / STATE_NAME).unlink(missing_ok=True)
        self.phase = "destroyed"

    # -- готовность, опрос, измерения -----------------------------------------------------

    def _node(self, node_id: str) -> Node:
        assert self.topology is not None
        return next(item for item in self.topology.nodes if item.id == node_id)

    def fetch_http(self, address: str, port: int, path: str = "/") -> tuple[int, str] | None:
        """GET из лаборатории от имени владельца; None, если гость не ответил."""
        if self.lab is None or self.topology is None:
            raise VMError("vm.not_created")
        host = str(ipaddress.IPv4Address(address))
        if not re.fullmatch(r"/[A-Za-z0-9._/-]{0,64}", path):
            raise VMError("vm.path_invalid")
        command = (
            [sys.executable, "--run-vm"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "polmon_l1_vm.cli"]
        )
        result = self.lab.run(
            [*command, "probe-http", host, str(int(port)), path],
            as_owner=True,
            check=False,
            timeout=8,
        )
        status, _, body = result.stdout.partition(" ")
        if result.returncode != 0 or not status.isdigit():
            return None
        return int(status), body

    def probe_http(self, address: str, port: int, node_id: str) -> bool:
        """Запрашивает страницу узла и сверяет идентичность именно этого клона."""
        if self.topology is None:
            raise VMError("vm.not_created")
        node = self._node(node_id)
        return self.fetch_http(address, port) == (200, f"POLMON {node.id} {node.uuid}\n")

    def _node_ready(self, node: Node) -> bool:
        address = str(node.interfaces[0].ipv4)
        if node.services:
            return self.probe_http(address, node.services[0].port, node.id)
        assert self.lab is not None
        return (
            self.lab.run(["ping", "-c", "1", "-W", "1", address], check=False, timeout=5).returncode
            == 0
        )

    def wait_ready(self) -> None:
        if self.phase != "started" or self.topology is None:
            raise VMError("vm.not_started")
        deadline = time.monotonic() + self.limits.boot_timeout_seconds
        pending = list(self.topology.nodes)
        while pending:
            for node in pending:
                if not alive(self.identities[node.id]):
                    raise VMError("vm.qemu_exited")
            pending = [node for node in pending if not self._node_ready(node)]
            if pending and time.monotonic() > deadline:
                raise VMError("vm.boot_timeout")
            if pending:
                time.sleep(1)

    def sample(self) -> dict:
        """Измерения из /proc и ip; недоступное значение — null, а не выдуманное число."""
        if self.topology is None:
            raise VMError("vm.not_created")
        nodes = {}
        for node in self.topology.nodes:
            identity = self.identities.get(node.id)
            entry: dict = {"pid": None, "cpu_seconds": None, "rss_bytes": None, "io": None}
            if identity and alive(identity):
                entry.update(self._process_sample(identity[0]))
            entry["interfaces"] = {
                interface.id: self._link_counters(node.id, interface.id)
                for interface in node.interfaces
            }
            overlay = self.directory / f"{node.id}.qcow2"
            entry["overlay_allocated_bytes"] = (
                overlay.stat().st_blocks * 512 if overlay.exists() else None
            )
            nodes[node.id] = entry
        return {
            "nodes": nodes,
            "guest_memory_mb_each": self.limits.memory_mb,
            "uptime_seconds": None
            if self.started_at is None
            else time.monotonic() - self.started_at,
            "admission": self.admission,
            "image": {
                key: self.image_info.get(key) for key in ("sha256", "distribution", "virtual_bytes")
            },
        }

    @staticmethod
    def _process_sample(pid: int) -> dict:
        out: dict = {"pid": pid, "cpu_seconds": None, "rss_bytes": None, "io": None}
        with contextlib.suppress(OSError, ValueError, IndexError):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            ticks = os.sysconf("SC_CLK_TCK")
            out["cpu_seconds"] = (int(fields[11]) + int(fields[12])) / ticks
        with contextlib.suppress(OSError, ValueError, IndexError):
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    out["rss_bytes"] = int(line.split()[1]) * 1024
        with contextlib.suppress(OSError, ValueError):
            counters = dict(
                line.split(": ") for line in Path(f"/proc/{pid}/io").read_text().splitlines()
            )
            out["io"] = {
                "read_bytes": int(counters["read_bytes"]),
                "write_bytes": int(counters["write_bytes"]),
            }
        return out

    def _link_counters(self, node_id: str, interface_id: str) -> dict | None:
        assert self.lab is not None
        tap = self.lab.names.taps[(node_id, interface_id)]
        try:
            result = self.lab.run(["ip", "-s", "-j", "link", "show", "dev", tap], timeout=5)
            stats = json.loads(result.stdout)[0]["stats64"]
            return {
                "rx_bytes": stats["rx"]["bytes"],
                "rx_packets": stats["rx"]["packets"],
                "tx_bytes": stats["tx"]["bytes"],
                "tx_packets": stats["tx"]["packets"],
            }
        except (RuntimeError, ValueError, KeyError, IndexError):
            return None

    def inspect(self) -> BackendInspection:
        return BackendInspection(
            self.name,
            frozenset(self.resources()),
            {
                "version": __version__,
                "runtime_implemented": True,
                "integration_verified": False,
                "phase": self.phase,
                "mode": self.mode,
                "qemu_pids": self.qemu_pids,
                "configured_memory_mb_per_vm": self.limits.memory_mb,
                "configured_vcpus_per_vm": 1,
            },
        )
