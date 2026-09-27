"""Compact formatting for dense operator displays (no Qt).

Numbers use a decimal point and IEC byte symbols (B, KiB, MiB) in every language; durations use
the current language's unit abbreviations (``unit.*``: ms/мс, s/с, min/мин, h/ч), see
docs/UI-GUIDE.md. Words come from the catalogs.
"""

from __future__ import annotations

import json
from datetime import datetime

from polmon.client.i18n import tr


def format_bytes(value: object) -> str:
    if not isinstance(value, int | float):
        return "—"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_seconds(value: object) -> str:
    if not isinstance(value, int | float):
        return "—"
    seconds = float(value)
    if seconds < 1:
        return tr("unit.ms", value=f"{seconds * 1000:.0f}")
    if seconds < 60:
        return tr("unit.s", value=f"{seconds:.1f}")
    minutes, rest = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return tr("unit.min_s", minutes=minutes, seconds=f"{rest:02d}")
    hours, minutes = divmod(minutes, 60)
    return tr("unit.h_min", hours=hours, minutes=f"{minutes:02d}")


def format_percent(value: object) -> str:
    return "—" if not isinstance(value, int | float) else f"{float(value):.1f} %"


def format_time(value: object) -> str:
    """ISO-8601 timestamp → local ``HH:MM:SS.mmm``; anything else is shown verbatim."""
    if not isinstance(value, str):
        return "—"
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return stamp.astimezone().strftime("%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}"


def format_datetime(value: object) -> str:
    if not isinstance(value, str):
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def duration_between(start: object, end: object) -> float | None:
    try:
        return (
            datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))
        ).total_seconds()
    except ValueError:
        return None


def compact_json(value: object, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def progress_text(
    completed: int, total: int, elapsed: float | None, eta: float | None, detail: str = ""
) -> str:
    """``step 3/10 · 30 % · 4.2 s elapsed · ETA 9.8 s · detail`` in the current language."""
    parts = [tr("progress.step", completed=completed, total=total)]
    if total:
        parts.append(f"{100 * completed / total:.0f} %")
    parts.append(tr("progress.elapsed", duration=format_seconds(elapsed)))
    parts.append(tr("progress.eta", duration=format_seconds(eta) if eta is not None else "—"))
    if detail:
        parts.append(detail)
    return " · ".join(parts)


def estimate_eta(completed: int, total: int, elapsed: float) -> float | None:
    if completed <= 0 or total <= completed:
        return 0.0 if total and completed >= total else None
    return elapsed / completed * (total - completed)
