"""Privilege-free topology inspection command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from polmon.core.errors import PolmonError
from polmon.topology import migrate_to_lab_profile
from polmon.topology.io import dump_topology, load_topology, parse_topology
from polmon.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="validate and inspect a polmon topology")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("path", nargs="?")
    parser.add_argument(
        "--migrate", metavar="PATH", help="atomically rewrite a v0.4 topology for lab-profile"
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--normalized", action="store_true", help="print normalized YAML")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = args.migrate or args.path
    if path is None:
        parser.error("a topology path or --migrate PATH is required")
    try:
        topology = (
            parse_topology(Path(path).read_text(encoding="utf-8"), migration=True)
            if args.migrate
            else load_topology(path)
        )
    except PolmonError as error:
        payload = {"error": error.code, "message": error.message, **error.details}
        print(json.dumps(payload), file=sys.stderr)
        return 2
    if args.migrate:
        migrated = migrate_to_lab_profile(topology)
        destination = Path(args.migrate)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(dump_topology(migrated), encoding="utf-8")
        temporary.replace(destination)
        print(json.dumps({"topology": migrated.id, "migrated": True, "path": str(destination)}))
        return 0
    if args.normalized:
        print(dump_topology(topology), end="")
    else:
        result = {
            "version": __version__,
            "topology": topology.id,
            "valid": True,
            "resources": topology.estimate_resources().model_dump(mode="json"),
        }
        print(json.dumps(result, indent=None if args.json else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
