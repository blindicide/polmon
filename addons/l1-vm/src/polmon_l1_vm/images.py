"""Pinned local image verification and independent copy-on-write disks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import urllib.request
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


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Перенаправления допускаются, но только на https: понижение до http отклоняется."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not newurl.startswith("https://"):
            raise VMError("vm.image_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_https(url: str):  # noqa: ANN202
    opener = urllib.request.build_opener(_HttpsOnly)
    return opener.open(url, timeout=30)


def acquire_image(destination: Path, manifest: ImageManifest, *, opener=_open_https) -> dict:
    """Скачивает образ из манифеста: только https, с лимитом размера и проверкой sha256.

    Файл появляется по месту назначения лишь после успешной проверки, только для чтения;
    существующий файл не перезаписывается.
    """
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise VMError("vm.image_exists")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".image-", suffix=".part", dir=destination.parent)
    temporary = Path(name)
    hasher, total = hashlib.sha256(), 0
    deadline = time.monotonic() + 900
    published = False
    try:
        with os.fdopen(fd, "wb") as stream, opener(manifest.source_url) as response:
            while chunk := response.read(1_048_576):
                total += len(chunk)
                if total > manifest.max_file_bytes or time.monotonic() > deadline:
                    raise VMError("vm.image_size")
                hasher.update(chunk)
                stream.write(chunk)
        if hasher.hexdigest() != manifest.sha256:
            raise VMError("vm.image_checksum")
        temporary.chmod(0o444)
        # Жёсткая ссылка не заменяет существующий файл, в отличие от rename.
        os.link(temporary, destination)
        published = True
    except OSError as error:
        raise VMError("vm.image_download") from error
    finally:
        # Windows refuses unlinking a read-only hard link; restore the published file after it.
        if os.name == "nt" and temporary.exists():
            temporary.chmod(0o600)
        temporary.unlink(missing_ok=True)
        if published:
            destination.chmod(0o444)
    return {
        "path": str(destination),
        "sha256": manifest.sha256,
        "bytes": total,
        "source_url": manifest.source_url,
    }
