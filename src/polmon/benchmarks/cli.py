"""``polmon-benchmark``: explicit, limit-bounded benchmark runs with retained raw results."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from polmon.benchmarks import l1, synthetic, target
from polmon.benchmarks.common import (
    DEFAULT_OUTPUT_DIR,
    BenchmarkLimitError,
    BenchmarkLimits,
    Progress,
    document,
    result_prefix,
    run_worker,
    write_results,
)
from polmon.core.errors import PolmonError
from polmon.topology.models import Topology
from polmon.version import __version__

EXIT_OK = 0
EXIT_NOT_RUN = 2
EXIT_ABORTED = 3


def _add_limits(parser: argparse.ArgumentParser, *, endpoints: int, namespaces: int) -> None:
    group = parser.add_argument_group("resource limits (every run is admitted against these)")
    group.add_argument("--max-endpoints", type=int, default=endpoints)
    group.add_argument("--max-namespaces", type=int, default=namespaces)
    group.add_argument(
        "--max-run-seconds", type=float, default=120.0, help="per-run wall-clock limit"
    )
    group.add_argument(
        "--max-incremental-mb",
        type=int,
        default=512,
        help="abort the suite when one run grows the measuring process beyond this",
    )
    group.add_argument("--memory-reserve-mb", type=int, default=256)


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--json", action="store_true", help="print the result document on stdout (progress: stderr)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polmon-benchmark",
        description="Run reproducible polmon benchmarks under explicit resource limits.",
    )
    parser.add_argument("--version", action="version", version=f"polmon {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    l0 = commands.add_parser("l0", help="synthetic L0 endpoints (rootless)")
    l0.add_argument("--counts", nargs="+", type=int, default=list(synthetic.DEFAULT_COUNTS))
    l0.add_argument("--large", action="store_true", help="also run the explicit 100/250 sizes")
    l0.add_argument("--repeats", type=int, default=3)
    l0.add_argument("--idle-seconds", type=float, default=0.5)
    _add_limits(l0, endpoints=0, namespaces=0)
    _add_output(l0)

    ns = commands.add_parser("l1", help="Linux namespace L1 endpoints (privileged lab)")
    ns.add_argument("--namespaces", type=int, default=2)
    ns.add_argument("--repeats", type=int, default=3)
    ns.add_argument("--idle-seconds", type=float, default=1.0)
    ns.add_argument("--ping-count", type=int, default=10)
    _add_limits(ns, endpoints=l1.MAX_NAMESPACES, namespaces=4)
    _add_output(ns)

    tg = commands.add_parser("target", help="Phase I target: 50 L0 + 2 L1 (privileged lab)")
    tg.add_argument("--l0", type=int, default=50)
    tg.add_argument("--l1", type=int, default=2)
    tg.add_argument("--repeats", type=int, default=3)
    tg.add_argument("--idle-seconds", type=float, default=1.0)
    _add_limits(tg, endpoints=64, namespaces=4)
    _add_output(tg)

    summary = commands.add_parser("summarize", help="render raw result JSON files as Markdown")
    summary.add_argument("files", nargs="+", type=Path)
    summary.add_argument("--output", type=Path, help="write Markdown here instead of stdout")
    return parser


def _limits(args: argparse.Namespace) -> BenchmarkLimits:
    return BenchmarkLimits(
        max_endpoints=args.max_endpoints,
        max_namespaces=args.max_namespaces,
        max_run_seconds=args.max_run_seconds,
        max_incremental_memory_mb=args.max_incremental_mb,
        memory_reserve_mb=args.memory_reserve_mb,
    )


def _validate_common(args: argparse.Namespace) -> None:
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if args.idle_seconds < 0 or args.idle_seconds > 60:
        raise SystemExit("--idle-seconds must be between 0 and 60")
    if args.max_run_seconds <= 0:
        raise SystemExit("--max-run-seconds must be positive")


def _emit(args: argparse.Namespace, payload: dict[str, object], started: datetime) -> None:
    json_path, csv_path = write_results(
        result_prefix(args.output_dir, str(payload["benchmark"]), started), payload
    )
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"status: {payload['status']}")
        print(f"JSON: {json_path}")
        if csv_path is not None:
            print(f"CSV: {csv_path}")


def _run_plan(
    args: argparse.Namespace,
    *,
    kind: str,
    plan: list[tuple[Topology, dict[str, object], str]],
    workload: dict[str, object],
    limitations: list[str],
    limits: BenchmarkLimits,
    precheck: Callable[[], tuple[bool, str]] | None = None,
) -> int:
    started = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    if precheck is not None:
        available, reason = precheck()
        if not available:
            payload = document(
                kind,
                workload=workload,
                limits=limits,
                limitations=limitations,
                measurements=[],
                started_at=started,
                status="not_run",
                error={"message": f"NOT RUN — environment unavailable: {reason}"},
            )
            _emit(args, payload, started)
            print(f"NOT RUN — environment unavailable: {reason}", file=sys.stderr)
            return EXIT_NOT_RUN
    progress = Progress(len(plan), label=f"benchmark {kind}")
    try:
        for topology, _, _ in plan:  # admit the whole plan before measuring anything
            limits.admit(topology)
        progress.update(0, "starting")
        for index, (_, params, detail) in enumerate(plan, start=1):
            row = run_worker(kind, params, timeout=limits.max_run_seconds)
            rows.append(row)
            limits.check_memory(row)
            progress.update(index, detail)
    except PolmonError as error:
        payload = document(
            kind,
            workload=workload,
            limits=limits,
            limitations=limitations,
            measurements=rows,
            started_at=started,
            status="aborted",
            error={"code": error.code, "message": error.message, "details": error.details},
        )
        _emit(args, payload, started)
        print(f"aborted: {error.message} {json.dumps(error.details)}", file=sys.stderr)
        return EXIT_ABORTED
    payload = document(
        kind,
        workload=workload,
        limits=limits,
        limitations=limitations,
        measurements=rows,
        started_at=started,
    )
    _emit(args, payload, started)
    incomplete = [row for row in rows if not row.get("cleanup_complete")]
    if incomplete:
        print(f"cleanup incomplete in {len(incomplete)} run(s)", file=sys.stderr)
        return EXIT_ABORTED
    return EXIT_OK


def command_l0(args: argparse.Namespace) -> int:
    _validate_common(args)
    counts = list(dict.fromkeys([*args.counts, *(synthetic.LARGE_COUNTS if args.large else ())]))
    if any(count > 50 for count in counts) and not args.large:
        raise SystemExit("endpoint counts above 50 require explicit --large")
    if args.max_endpoints == 0:
        args.max_endpoints = synthetic.MAX_COUNT if args.large else 50
    limits = _limits(args)
    plan = [
        (
            synthetic.build_topology(count),
            {"endpoint_count": count, "repeat": repeat, "idle_seconds": args.idle_seconds},
            f"endpoints={count} repeat={repeat}",
        )
        for count in counts
        for repeat in range(1, args.repeats + 1)
    ]
    workload = {
        "fidelity": synthetic.FIDELITY,
        "endpoint_counts": counts,
        "repeats": args.repeats,
        "idle_seconds_per_run": args.idle_seconds,
        "traffic": "two rounds of one ICMP echo from the first endpoint to every other "
        "endpoint (round 1 resolves ARP, round 2 uses the ARP cache)",
        "isolation": "one fresh Python process per run",
    }
    return _run_plan(
        args,
        kind="l0",
        plan=plan,
        workload=workload,
        limitations=synthetic.LIMITATIONS,
        limits=limits,
    )


def command_l1(args: argparse.Namespace) -> int:
    _validate_common(args)
    if not 1 <= args.ping_count <= 100:
        raise SystemExit("--ping-count must be between 1 and 100")
    limits = _limits(args)
    topology = l1.build_topology(args.namespaces)
    plan = [
        (
            topology,
            {
                "namespace_count": args.namespaces,
                "repeat": repeat,
                "idle_seconds": args.idle_seconds,
                "ping_count": args.ping_count,
            },
            f"namespaces={args.namespaces} repeat={repeat}",
        )
        for repeat in range(1, args.repeats + 1)
    ]
    workload = {
        "fidelity": l1.FIDELITY,
        "namespace_count": args.namespaces,
        "services": "one built-in static HTTP service in the last namespace",
        "repeats": args.repeats,
        "idle_seconds_per_run": args.idle_seconds,
        "traffic": f"{args.ping_count} kernel ICMP echoes at 0.2 s intervals, client to peer",
        "isolation": "one fresh Python process per run",
    }
    return _run_plan(
        args,
        kind="l1",
        plan=plan,
        workload=workload,
        limitations=l1.LIMITATIONS,
        limits=limits,
        precheck=l1.namespace_environment_available,
    )


def command_target(args: argparse.Namespace) -> int:
    _validate_common(args)
    limits = _limits(args)
    topology = target.build_topology(args.l0, args.l1)
    plan = [
        (
            topology,
            {
                "l0_count": args.l0,
                "l1_count": args.l1,
                "repeat": repeat,
                "idle_seconds": args.idle_seconds,
            },
            f"l0={args.l0} l1={args.l1} repeat={repeat}",
        )
        for repeat in range(1, args.repeats + 1)
    ]
    workload = {
        "fidelity": target.FIDELITY,
        "l0_count": args.l0,
        "l1_count": args.l1,
        "services": "one built-in static HTTP service in every L1 namespace",
        "repeats": args.repeats,
        "idle_seconds_per_run": args.idle_seconds,
        "traffic": "one L0-to-L1 echo per L0 endpoint across the TAP, one L0-to-L0 echo per "
        "L0 endpoint, five kernel L1-to-L1 echoes",
        "target": "approximately 1 GB incremental memory for 50 L0 + 2 L1 (specification §2)",
        "isolation": "one fresh Python process per run",
    }
    return _run_plan(
        args,
        kind="target",
        plan=plan,
        workload=workload,
        limitations=target.LIMITATIONS,
        limits=limits,
        precheck=l1.namespace_environment_available,
    )


# ---------------------------------------------------------------------------------------------
# Markdown summaries generated only from raw result files.

MIB = 1_048_576


def _stat(rows: list[dict[str, object]], key: str) -> tuple[float, float, float] | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), int | float)]
    if not values:
        return None
    return statistics.median(values), min(values), max(values)


def _cell(rows: list[dict[str, object]], key: str, scale: float = 1.0, digits: int = 2) -> str:
    stat = _stat(rows, key)
    if stat is None:
        return "n/a"
    median, low, high = (f"{value * scale:.{digits}f}" for value in stat)
    if len(rows) == 1 or low == high:
        return median
    return f"{median} ({low}–{high})"


def _all(rows: list[dict[str, object]], key: str) -> str:
    values = [row.get(key) for row in rows]
    return "yes" if values and all(value is True for value in values) else "NO"


def _cleanup(rows: list[dict[str, object]]) -> str:
    return _all(rows, "cleanup_complete")


L0_COLUMNS = [
    ("create ms", "creation_seconds", 1_000, 2),
    ("teardown ms", "teardown_seconds", 1_000, 2),
    ("incr. RSS MiB", "incremental_memory_bytes", 1 / MIB, 2),
    ("peak incr. MiB", "peak_incremental_memory_bytes", 1 / MIB, 2),
    ("heap KiB", "python_heap_deployed_bytes", 1 / 1024, 1),
    ("heap B/endpoint", "python_heap_bytes_per_endpoint", 1, 0),
    ("idle CPU ms", "idle_cpu_seconds", 1_000, 2),
    ("µs CPU/echo", "traffic_cpu_microseconds_per_echo", 1, 1),
    ("p50 ms", "latency_p50_ms", 1, 3),
    ("p95 ms", "latency_p95_ms", 1, 3),
    ("loss %", "packet_loss_percent", 1, 1),
    ("CPU %", "cpu_utilization_percent", 1, 1),
]
L1_COLUMNS = [
    ("create s", "creation_seconds", 1, 3),
    ("service ready s", "service_ready_seconds", 1, 3),
    ("teardown s", "teardown_seconds", 1, 3),
    ("service tree MiB", "service_tree_rss_bytes", 1 / MIB, 1),
    ("host ΔMemAvail MiB", "host_available_memory_delta_bytes", 1 / MIB, 1),
    ("service idle CPU ms", "service_idle_cpu_seconds", 1_000, 1),
    ("RTT avg ms", "ping_rtt_avg_ms", 1, 3),
    ("loss %", "ping_loss_percent", 1, 1),
]
TARGET_COLUMNS = [
    ("deploy s", "deployment_seconds", 1, 3),
    ("teardown s", "teardown_seconds", 1, 3),
    ("controller MiB", "controller_incremental_rss_bytes", 1 / MIB, 1),
    ("services MiB", "service_tree_rss_bytes", 1 / MIB, 1),
    ("attributed MiB", "attributed_incremental_memory_bytes", 1 / MIB, 1),
    ("host ΔMemAvail MiB", "host_available_memory_delta_bytes", 1 / MIB, 1),
    ("L0→L1 loss %", "l0_to_l1_loss_percent", 1, 1),
    ("L0→L1 p50 ms", "l0_to_l1_latency_p50_ms", 1, 3),
    ("L0→L0 p50 ms", "l0_to_l0_latency_p50_ms", 1, 3),
    ("L1→L1 RTT ms", "l1_to_l1_rtt_avg_ms", 1, 3),
]


def _table(
    groups: dict[str, list[dict[str, object]]],
    group_label: str,
    columns: list[tuple[str, str, float, int]],
    extra: list[tuple[str, Callable[[list[dict[str, object]]], str]]],
) -> list[str]:
    header = [group_label, "runs", *(name for name, *_ in columns), *(name for name, _ in extra)]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for label, rows in groups.items():
        cells = [label, str(len(rows))]
        cells += [_cell(rows, key, scale, digits) for _, key, scale, digits in columns]
        cells += [render(rows) for _, render in extra]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def summarize(payload: dict[str, object], source: str) -> list[str]:
    kind = payload.get("benchmark")
    rows = [row for row in payload.get("measurements", []) if isinstance(row, dict)]
    hardware = payload.get("hardware", {})
    assert isinstance(hardware, dict)
    lines = [
        f"### `{kind}` — {source}",
        "",
        f"- polmon {payload.get('polmon_version')} "
        f"(commit {str((payload.get('source') or {}).get('commit'))[:12]}"
        f"{', dirty tree' if (payload.get('source') or {}).get('dirty') else ''}), "
        f"status **{payload.get('status')}**, started {payload.get('started_at')}",
        f"- host: {hardware.get('cpu_model')}, {hardware.get('logical_cpu_count')} logical CPUs, "
        f"{(hardware.get('total_memory_bytes') or 0) / MIB / 1024:.1f} GiB RAM, "
        f"kernel {hardware.get('kernel')}, Python {hardware.get('python')}",
        f"- workload: {json.dumps(payload.get('workload'), ensure_ascii=False, sort_keys=True)}",
    ]
    if payload.get("error"):
        lines.append(f"- error: {json.dumps(payload['error'], ensure_ascii=False)}")
    lines.append("")
    if not rows:
        lines += ["No measurements recorded.", ""]
        return lines
    lines.append("Median (min–max) across repeats.")
    lines.append("")
    if kind == "l0":
        groups: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            groups.setdefault(str(row["endpoint_count"]), []).append(row)
        lines += _table(groups, "L0 endpoints", L0_COLUMNS, [("cleanup", _cleanup)])
    elif kind == "l1":
        groups = {str(rows[0]["namespace_count"]): rows}
        lines += _table(groups, "namespaces", L1_COLUMNS, [("cleanup", _cleanup)])
    elif kind == "target":
        groups = {f"{rows[0]['l0_count']} L0 + {rows[0]['l1_count']} L1": rows}
        lines += _table(
            groups,
            "topology",
            TARGET_COLUMNS,
            [
                ("≤1 GiB (attributed)", lambda r: _all(r, "within_target_attributed")),
                ("≤1 GiB (host Δ)", lambda r: _all(r, "within_target_host_delta")),
                ("cleanup", _cleanup),
            ],
        )
    else:
        lines.append(f"Unknown benchmark kind {kind!r}; raw rows retained in the JSON file.")
    lines.append("")
    return lines


def _display_path(path: Path) -> str:
    """Repository-relative path when possible, so summaries never embed local home paths."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def command_summarize(args: argparse.Namespace) -> int:
    lines: list[str] = []
    for path in args.files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        lines += summarize(payload, _display_path(path))
    text = "\n".join(lines).rstrip() + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "l0": command_l0,
        "l1": command_l1,
        "target": command_target,
        "summarize": command_summarize,
    }
    try:
        return handlers[args.command](args)
    except (ValueError, BenchmarkLimitError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ABORTED


if __name__ == "__main__":
    raise SystemExit(main())
