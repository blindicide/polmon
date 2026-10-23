"""Read-only planning CLI for the optional VM-backed L1 scaffold."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from polmon.topology import load_topology
from polmon.version import __version__
from polmon_l1_vm.backend import VMBackend, readiness
from polmon_l1_vm.images import ImageManifest, VMError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optional VM-backed L1 scaffold (no runtime)")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("readiness")
    plan = sub.add_parser("plan")
    plan.add_argument("--topology", type=Path, required=True)
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--image", type=Path, required=True)
    plan.add_argument("--directory", type=Path, required=True)
    # Recognize previous prototype commands solely to return a stable refusal.
    for operation in ("run", "recover", "acquire-image", "verify-image", "inspect"):
        sub.add_parser(operation).add_argument("arguments", nargs=argparse.REMAINDER)
    args, unknown = parser.parse_known_args(argv)
    if unknown and args.action in ("plan", "readiness"):
        parser.error("unrecognized arguments: " + " ".join(unknown))
    try:
        if args.action == "readiness":
            print(json.dumps(readiness()))
            return 2
        if args.action != "plan":
            raise VMError("vm.scaffold_only")
        if args.manifest.stat().st_size > 16384:
            raise VMError("vm.manifest_size")
        manifest = ImageManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        backend = VMBackend(base=args.image, manifest=manifest, directory=args.directory)
        print(json.dumps(backend.plan(load_topology(args.topology))))
        return 0
    except Exception as error:
        code = error.code if isinstance(error, VMError) else type(error).__name__
        print(json.dumps({"error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
