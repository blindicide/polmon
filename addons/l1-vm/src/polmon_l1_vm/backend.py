"""Non-executing contracts for a future optional VM-backed L1 backend."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from pydantic import Field

from polmon.backends.namespace.runner import CommandRunner
from polmon.orchestration.base import BackendInspection, ExecutionBackend
from polmon.topology.models import NodeClass, StrictModel, Topology
from polmon.version import __version__
from polmon_l1_vm.images import ImageManifest, VMError


class VMLimits(StrictModel):
    max_vms: int = Field(default=2, ge=1, le=4)
    memory_mb: int = Field(default=256, ge=128, le=512)
    max_total_memory_mb: int = Field(default=768, ge=256, le=1536)
    memory_reserve_mb: int = Field(default=256, ge=256, le=4096)
    disk_reserve_mb: int = Field(default=512, ge=128, le=4096)
    max_total_disk_mb: int = Field(default=4096, ge=128, le=8192)
    boot_timeout_seconds: int = Field(default=90, ge=10, le=180)
    # One vCPU per guest; no unbounded TCG fallback or overcommit.
    max_vcpus: int = Field(default=2, ge=1, le=4)


def readiness() -> dict:
    missing = []
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        missing.append("vm.linux_x86_64_required")
    for name, code in [
        ("qemu-system-x86_64", "vm.qemu_missing"),
        ("qemu-img", "vm.qemu_img_missing"),
        ("genisoimage", "vm.seed_tool_missing"),
        ("ip", "vm.ip_missing"),
        ("sudo", "vm.sudo_missing"),
        ("setpriv", "vm.setpriv_missing"),
        ("ping", "vm.ping_missing"),
    ]:
        if shutil.which(name) is None:
            missing.append(code)
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        missing.append("vm.kvm_unavailable")
    if not os.access("/dev/net/tun", os.R_OK | os.W_OK):
        missing.append("vm.tun_unavailable")
    return {
        "version": __version__,
        "backend": "l1-vm-addon",
        "ready": False,
        "runtime_implemented": False,
        "missing": [*missing, "vm.scaffold_only"],
        "fidelity": "full Linux VM; namespace L1 remains unchanged",
        "integration_verified": False,
    }


class VMBackend(ExecutionBackend):
    """Validate and plan only; every runtime lifecycle operation fails before mutation."""

    name = "l1-vm-addon"

    def __init__(
        self,
        *,
        base: Path,
        manifest: ImageManifest,
        directory: Path,
        limits: VMLimits | None = None,
        runner: CommandRunner | None = None,
    ):
        self.base, self.manifest = base.resolve(), manifest
        self.directory = directory.resolve()
        if any(c in str(path) for path in (self.base, self.directory) for c in ",\n\r"):
            raise VMError("vm.path_invalid")
        self.limits = limits or VMLimits()
        self.runner = runner or CommandRunner()

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
                # Explicit VM budget in VMLimits, never silently reinterpret namespace estimates.
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
            "runtime_implemented": False,
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
            "unavailable": ["guest_boot", "guest_metrics", "runtime_admission", "recovery"],
        }

    def create(self, topology: Topology) -> set[str]:
        self.validate(topology)
        raise VMError("vm.scaffold_only")

    def start(self) -> None:
        raise VMError("vm.scaffold_only")

    def stop(self) -> None:
        raise VMError("vm.scaffold_only")

    def destroy(self) -> None:
        raise VMError("vm.scaffold_only")

    def wait_ready(self) -> None:
        raise VMError("vm.scaffold_only")

    def probe_http(self, address: str, port: int, node_id: str) -> bool:
        raise VMError("vm.scaffold_only")

    def sample(self) -> dict:
        raise VMError("vm.scaffold_only")

    def inspect(self) -> BackendInspection:
        return BackendInspection(
            self.name,
            frozenset(),
            {
                "version": __version__,
                "runtime_implemented": False,
                "integration_verified": False,
                "guest_memory_bytes": None,
                "uptime_seconds": None,
                "configured_memory_mb_per_vm": self.limits.memory_mb,
                "configured_vcpus_per_vm": 1,
            },
        )
