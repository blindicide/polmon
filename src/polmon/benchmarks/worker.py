"""Fresh-process measurement worker: ``python -m polmon.benchmarks.worker KIND PARAMS_JSON``.

Prints exactly one JSON object (the measurement row) on the last stdout line.
"""

from __future__ import annotations

import json
import sys


def measure(kind: str, params: dict[str, object]) -> dict[str, object]:
    if kind == "l0":
        from polmon.benchmarks.synthetic import run_once

        return run_once(
            int(params["endpoint_count"]), int(params["repeat"]), float(params["idle_seconds"])
        )
    if kind == "l1":
        from polmon.benchmarks.l1 import run_once

        return run_once(
            int(params["namespace_count"]),
            int(params["repeat"]),
            float(params["idle_seconds"]),
            int(params["ping_count"]),
        )
    if kind == "target":
        from polmon.benchmarks.target import run_once

        return run_once(
            int(params["l0_count"]),
            int(params["l1_count"]),
            int(params["repeat"]),
            float(params["idle_seconds"]),
        )
    raise ValueError(f"unknown benchmark kind '{kind}'")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print("usage: python -m polmon.benchmarks.worker KIND PARAMS_JSON", file=sys.stderr)
        return 2
    params = json.loads(arguments[1])
    if not isinstance(params, dict):
        print("PARAMS_JSON must be an object", file=sys.stderr)
        return 2
    row = measure(arguments[0], params)
    print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
