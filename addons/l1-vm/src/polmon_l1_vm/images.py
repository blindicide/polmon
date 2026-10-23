"""Pinned local image verification and independent copy-on-write disks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from pydantic import Field

from polmon.backends.namespace.runner import CommandRunner
from polmon.topology.models import StrictModel


class VMError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ImageManifest(StrictModel):
    """An operator-reviewed digest is mandatory; never resolve a moving 'latest' image."""

    schema_version: int = Field(default=1, ge=1, le=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(pattern=r"^https://[^\s]+$", max_length=1024)
    distribution: str = Field(pattern=r"^alpine-[0-9.]+-x86_64-bios-cloudinit$")
    license_notice: str = Field(min_length=1, max_length=1024)
    max_file_bytes: int = Field(default=536_870_912, ge=1, le=1_073_741_824)
    max_virtual_bytes: int = Field(default=2_147_483_648, ge=1, le=4_294_967_296)


def digest(path: Path, *, limit: int) -> str:
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            total += len(chunk)
            if total > limit:
                raise VMError("vm.image_size")
            h.update(chunk)
    return h.hexdigest()


def verify_image(path: Path, manifest: ImageManifest, runner: CommandRunner) -> dict:
    """Hash before invoking qemu-img; refuse backing chains and external data files."""
    if path.is_symlink() or not path.is_file():
        raise VMError("vm.image_missing")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o222:
        raise VMError("vm.base_not_readonly")
    if digest(path, limit=manifest.max_file_bytes) != manifest.sha256:
        raise VMError("vm.image_checksum")
    result = runner.run(["qemu-img", "info", "--output=json", "-f", "qcow2", str(path)], timeout=30)
    data = json.loads(result.stdout)
    specific = data.get("format-specific", {}).get("data", {})
    if (
        data.get("format") != "qcow2"
        or data.get("backing-filename")
        or specific.get("data-file")
        or specific.get("encrypt")
        or not 0 < data.get("virtual-size", 0) <= manifest.max_virtual_bytes
    ):
        raise VMError("vm.image_format")
    return {
        "sha256": manifest.sha256,
        "virtual_bytes": data["virtual-size"],
        "allocated_bytes": info.st_blocks * 512,
        "file_bytes": info.st_size,
        "source_url": manifest.source_url,
        "distribution": manifest.distribution,
    }


class OverlayStore:
    def __init__(self, directory: Path, base: Path, runner: CommandRunner):
        self.directory, self.base, self.runner = directory, base.resolve(), runner
        self.owned: set[Path] = set()

    def create(self, node: str) -> Path:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", node):
            raise VMError("vm.node_id")
        path = self.directory / f"{node}.qcow2"
        # Reserve exclusively so qemu-img never truncates an operator's file.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        self.owned.add(path)
        try:
            self.runner.run(
                [
                    "qemu-img",
                    "create",
                    "-q",
                    "-f",
                    "qcow2",
                    "-F",
                    "qcow2",
                    "-b",
                    str(self.base),
                    str(path),
                ],
                timeout=30,
            )
        except BaseException:
            path.unlink(missing_ok=True)
            self.owned.discard(path)
            raise
        return path

    def destroy(self) -> None:
        for path in list(self.owned):
            path.unlink(missing_ok=True)
            self.owned.remove(path)


def acquire_image(destination: Path, manifest: ImageManifest) -> dict:
    """Acquisition is deferred until an authorized image/runtime implementation exists."""
    raise VMError("vm.scaffold_only")
