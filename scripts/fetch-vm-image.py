#!/usr/bin/env python3
"""Кладёт закреплённый образ гостя в packaging/vm-image: оттуда он попадает в сборку программы."""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polmon.api.vm import IMAGE_NAME, MANIFEST  # noqa: E402

TARGET = ROOT / "packaging/vm-image" / IMAGE_NAME


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def main() -> int:
    if TARGET.is_file() and digest(TARGET) == MANIFEST["sha256"]:
        print(f"образ уже на месте: {TARGET}")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    partial = TARGET.with_suffix(".part")
    with (
        urllib.request.urlopen(MANIFEST["source_url"], timeout=60) as response,  # noqa: S310
        partial.open("wb") as sink,
    ):
        shutil.copyfileobj(response, sink)
    if digest(partial) != MANIFEST["sha256"]:
        partial.unlink()
        print("контрольная сумма скачанного образа не совпала", file=sys.stderr)
        return 1
    partial.replace(TARGET)
    print(f"образ сохранён: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
