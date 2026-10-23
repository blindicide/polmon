#!/usr/bin/env python3
"""Acquire the digest-pinned Linux guest image for native packaging; never boot it."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "addons/l1-vm/src")]

from polmon_l1_vm.images import ImageManifest, VMError, acquire_image, digest  # noqa: E402

from polmon.api.vm import IMAGE_NAME, MANIFEST  # noqa: E402

TARGET = ROOT / "packaging/vm-image" / IMAGE_NAME


def main() -> int:
    manifest = ImageManifest.model_validate(MANIFEST)
    if TARGET.is_symlink():
        raise VMError("vm.image_exists")
    if TARGET.exists():
        if digest(TARGET, limit=manifest.max_file_bytes) != manifest.sha256:
            raise VMError("vm.image_checksum")
        TARGET.chmod(0o444)
    else:
        acquire_image(TARGET, manifest)
    print(f"verified image: {TARGET.name} sha256={manifest.sha256} bytes={TARGET.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
