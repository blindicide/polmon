"""Privilege-free topology inspection command."""

from __future__ import annotations

import argparse
import json
import sys

from polmon.core.errors import PolmonError
from polmon.topology.io import dump_topology, load_topology
from polmon.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="validate and inspect a polmon topology")
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--normalized", action="store_true", help="print normalized YAML")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        topology = load_topology(args.path)
    except PolmonError as error:
        payload = {"error": error.code, "message": error.message, **error.details}
        print(json.dumps(payload), file=sys.stderr)
        return 2
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
