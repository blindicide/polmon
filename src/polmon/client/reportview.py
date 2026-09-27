"""Client-rendered, localized Markdown views of experiment reports and benchmark results.

The backend's own Markdown artifacts are English documents (kept verbatim for *Save Markdown*);
the client renders the same facts from the JSON documents in the UI language. Identifiers,
numbers and JSON blocks are machine data and are shown as they are.
"""

from __future__ import annotations

import json

from polmon.client.errors import backend_message
from polmon.client.formatting import format_bytes, format_datetime
from polmon.client.i18n import has, status_label, tr, tr_n


def _code(value: object) -> str:
    return f"`{value}`" if value not in (None, "") else "—"


def _json_block(value: object) -> list[str]:
    return ["```json", json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), "```"]


def report_errors(report: dict[str, object]) -> list[str]:
    details = report.get("error_details")
    if isinstance(details, list) and details:
        return [
            str(backend_message(item.get("message_code"), item.get("params"),
                                str(item.get("message"))))
            for item in details
            if isinstance(item, dict)
        ]
    return [str(backend_message(None, None, str(item))) for item in report.get("errors") or []]  # type: ignore[union-attr]


def experiment_markdown(report: dict[str, object]) -> str:
    execution = report.get("execution") or {}
    capture = report.get("capture") or {}
    assert isinstance(execution, dict) and isinstance(capture, dict)
    comparisons = [
        item for item in report.get("expected_vs_actual") or []  # type: ignore[union-attr]
        if isinstance(item, dict)
    ]
    comparison_lines = [
        "- "
        + tr(
            "reportview.comparison",
            role=tr(f"condition.role.{item.get('role')}"),
            check=f"`{item.get('action')}.{item.get('field')} == {item.get('expected')}`",
            actual=_code(item.get("actual")),
            outcome=status_label(str(item.get("outcome", "")).replace(" ", "_")),
        )
        for item in comparisons
    ] or [f"- {tr('reportview.none')}"]
    errors = [f"- {item}" for item in report_errors(report)] or [f"- {tr('reportview.none')}"]
    resources = report.get("resource_statistics") or []
    return "\n".join(
        [
            f"### {tr('reportview.title', experiment=report.get('experiment_id'))}",
            "",
            f"- {tr('reportview.status')}: **{status_label(report.get('status'))}**",
            f"- {tr('reportview.version')}: {_code(report.get('polmon_version'))}",
            f"- {tr('reportview.started')}: {format_datetime(execution.get('started_at'))}",
            f"- {tr('reportview.finished')}: {format_datetime(execution.get('finished_at'))}",
            f"- {tr('reportview.cleanup')}: "
            + (tr("common.yes") if execution.get("cleanup_performed") else tr("common.no")),
            "",
            f"#### {tr('reportview.comparisons')}",
            "",
            *comparison_lines,
            "",
            f"#### {tr('reportview.errors')}",
            "",
            *errors,
            "",
            f"#### {tr('reportview.capture')}",
            "",
            f"- {tr('capture.frames')}: {_code(capture.get('frame_count'))}",
            f"- {tr('capture.bytes')}: {format_bytes(capture.get('captured_bytes'))}",
            f"- {tr('capture.dropped')}: {_code(capture.get('dropped_frames'))}",
            f"- {tr('capture.truncated')}: {_code(capture.get('truncated_frames'))}",
            "",
            f"#### {tr('reportview.resources')}",
            "",
            *_json_block(resources),
            "",
            f"#### {tr('reportview.topology')}",
            "",
            *_json_block(report.get("topology")),
            "",
            f"#### {tr('reportview.scenario')}",
            "",
            *_json_block(report.get("scenario")),
            "",
        ]
    )


# Benchmark document fields → the labels of the benchmark form that sets them.
BENCHMARK_FIELDS = {
    "endpoint_counts": "benchmarks.counts",
    "namespace_count": "benchmarks.namespaces",
    "l0_count": "benchmarks.target_l0",
    "l1_count": "benchmarks.target_l1",
    "repeats": "benchmarks.repeats",
    "idle_seconds_per_run": "benchmarks.idle",
    "settle_seconds_between_runs": "benchmarks.settle",
    "max_endpoints": "benchmarks.max_endpoints",
    "max_namespaces": "benchmarks.max_namespaces",
    "max_run_seconds": "benchmarks.max_run",
    "max_incremental_memory_mb": "benchmarks.max_incremental",
    "memory_reserve_mb": "benchmarks.reserve",
}


def _field(key: str, value: object) -> str:
    """``- label: value unit``; a field this client does not know keeps its machine name."""
    label = BENCHMARK_FIELDS.get(key)
    shown = _code(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        if key.endswith("_mb"):
            shown = _code(f"{value} MiB")
        elif "seconds" in key:
            shown = _code(tr("unit.s", value=f"{value:g}"))
    return f"- {tr(label) if label else _code(key)}: {shown}"


def benchmark_markdown(document: dict[str, object]) -> str:
    kind = str(document.get("benchmark") or "")
    workload = document.get("workload") or {}
    limits = document.get("limits") or {}
    hardware = document.get("hardware") or {}
    assert isinstance(workload, dict) and isinstance(limits, dict) and isinstance(hardware, dict)
    measurements = [row for row in document.get("measurements") or [] if isinstance(row, dict)]  # type: ignore[union-attr]
    kind_key = f"benchmark.kind.{kind}"
    lines = [
        f"### {tr('reportview.benchmark.title', kind=tr(kind_key) if has(kind_key) else kind)}",
        "",
        f"- {tr('reportview.status')}: **{status_label(document.get('status'))}**",
        f"- {tr('reportview.started')}: {format_datetime(document.get('started_at'))}",
        f"- {tr('reportview.finished')}: {format_datetime(document.get('finished_at'))}",
        f"- {tr('reportview.version')}: {_code(document.get('polmon_version'))}",
        f"- {tr('reportview.benchmark.measurements')}: "
        + tr_n("count.measurements", len(measurements)),
    ]
    error = document.get("error")
    if isinstance(error, dict):
        message = backend_message(error.get("message_code"), error.get("params"),
                                  str(error.get("message") or ""))
        lines += ["", f"**{message}**"]
    workload_values = {
        key: value for key, value in workload.items() if isinstance(value, int | float | list)
    }
    lines += ["", f"#### {tr('reportview.benchmark.workload')}", ""]
    lines += [_field(key, value) for key, value in workload_values.items()] or [
        f"- {tr('reportview.none')}"
    ]
    lines += ["", f"#### {tr('reportview.benchmark.limits')}", ""]
    lines += [_field(key, value) for key, value in limits.items()] or [
        f"- {tr('reportview.none')}"
    ]
    lines += [
        "",
        f"#### {tr('reportview.benchmark.hardware')}",
        "",
        f"- {tr('reportview.benchmark.cpu')}: {_code(hardware.get('cpu_model'))}"
        f" × {hardware.get('logical_cpu_count', '—')}",
        f"- {tr('reportview.benchmark.memory')}: "
        f"{format_bytes(hardware.get('total_memory_bytes'))}",
        f"- {tr('reportview.benchmark.kernel')}: {_code(hardware.get('kernel'))}",
        "",
        f"#### {tr('reportview.benchmark.fidelity')}",
        "",
        tr(f"{kind_key}.limitation") if has(f"{kind_key}.limitation") else tr("reportview.none"),
        "",
    ]
    return "\n".join(lines)


__all__ = ["benchmark_markdown", "experiment_markdown", "report_errors"]
