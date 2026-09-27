"""Formatting of values for dense operator displays (no Qt).

Quantities are localized: unit words and symbols come from the catalogs (``unit.*``), with
plural agreement in Russian (``1 минута``, ``2 минуты``, ``5 минут``, ``4,2 секунды``) and the
language's decimal separator. A number and its unit are joined by a no-break space so they never
wrap apart. :class:`Quantity` values render on display, so a quantity inside a :class:`Msg`
follows a language switch. Identifiers, JSON and timestamps are never localized.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from polmon.client.i18n import tr, tr_n

NBSP = "\u00a0"
BYTE_UNITS = ("unit.kib", "unit.mib", "unit.gib", "unit.tib")
# Every ``unit.<name>`` of the catalogs (plural entries where a language declines the word).
UNITS = ("millisecond", "second", "minute", "hour", "byte", "millicore", "kib", "mib", "gib", "tib")


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def format_number(value: float, decimals: int = 1) -> str:
    """``4.2`` → ``4,2`` in Russian; ``decimals`` places, trailing ``,0`` kept."""
    text = f"{value:.{decimals}f}" if decimals else f"{round(value):d}"
    return text.replace(".", tr("unit.decimal_separator")).replace("-", "\u2212")


def unit_word(unit: str, count: float, *, fraction: bool = False) -> str:
    """The word or symbol of ``unit.<unit>`` agreeing with ``count``; a number shown with a
    fraction (``2,0``, ``0,5``) takes the fraction form (``секунды``) whatever its value."""
    return tr_n(f"unit.{unit}", 0.5 if fraction else count)


def _amount(count: float, unit: str, decimals: int = 0) -> str:
    shown = format_number(count, decimals)
    return f"{shown}{NBSP}{unit_word(unit, count, fraction=decimals > 0)}"


def format_duration(value: object, *, milliseconds: bool = True) -> str:
    """``250 миллисекунд``, ``4,2 секунды``, ``5 минут``, ``1 минута 15 секунд``, ``1 час
    5 минут`` (English: ``250 ms``, ``4.2 s``, ``5 min``, ``1 min 15 s``, ``1 h 5 min``).
    Without ``milliseconds`` a short duration reads ``0,3 секунды`` (compact tiles)."""
    if not _is_number(value):
        return "—"
    seconds = float(value)  # type: ignore[arg-type]
    sign = "\u2212" if seconds < 0 else ""
    seconds = abs(seconds)
    if milliseconds and round(seconds * 1000) < 1000:
        return sign + _amount(round(seconds * 1000), "millisecond")
    tenths = round(seconds, 1)
    if tenths < 60:
        whole = tenths == int(tenths)
        return sign + _amount(int(tenths) if whole else tenths, "second", 0 if whole else 1)
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        parts = [_amount(minutes, "minute")] + ([_amount(rest, "second")] if rest else [])
    else:
        hours, minutes = divmod(minutes, 60)
        parts = [_amount(hours, "hour")] + ([_amount(minutes, "minute")] if minutes else [])
    return sign + " ".join(parts)



def format_bytes(value: object) -> str:
    """``512 байт``, ``3,0 МиБ`` (English: ``512 B``, ``3.0 MiB``)."""
    if not _is_number(value):
        return "—"
    size = float(value)  # type: ignore[arg-type]
    if abs(size) < 1024:
        return _amount(int(size), "byte")
    for key in BYTE_UNITS:
        size /= 1024
        if abs(size) < 1024 or key == BYTE_UNITS[-1]:
            break
    return f"{format_number(size, 1)}{NBSP}{tr(key)}"


def format_mebibytes(value: object) -> str:
    """A value counted in MiB (limits, estimates): ``512 МиБ``, ``12,5 МиБ``."""
    if not _is_number(value):
        return "—" if value is None else str(value)
    amount = float(value)  # type: ignore[arg-type]
    decimals = 0 if amount == int(amount) else 1
    return f"{format_number(amount, decimals)}{NBSP}{tr('unit.mib')}"


def format_millicores(value: object) -> str:
    """CPU in thousandths of a core: ``250 миллиядер`` (English: ``250 mCPU``)."""
    if not _is_number(value):
        return "—" if value is None else str(value)
    return _amount(int(value), "millicore")  # type: ignore[call-overload]


def format_percent(value: object, decimals: int = 1) -> str:
    if not _is_number(value):
        return "—"
    return f"{format_number(float(value), decimals)}{NBSP}%"  # type: ignore[arg-type]


class Quantity:
    """A number with a unit, rendered in the current language whenever it is displayed."""

    __slots__ = ("render", "value")

    def __init__(self, render: Callable[[object], str], value: object) -> None:
        self.render, self.value = render, value

    def __str__(self) -> str:
        return self.render(self.value)

    def __repr__(self) -> str:
        return f"Quantity({self.render.__name__}, {self.value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Quantity) and (self.render, self.value) == (
            other.render,
            other.value,
        )

    __hash__ = None  # type: ignore[assignment]


def duration(value: object) -> Quantity:
    return Quantity(format_duration, value)


def size(value: object) -> Quantity:
    return Quantity(format_bytes, value)


def mebibytes(value: object) -> Quantity:
    return Quantity(format_mebibytes, value)


def quantity_for(name: str, value: object) -> object:
    """A lazily localized value for a parameter named after its unit (``seconds``,
    ``*_seconds``, ``*_bytes``, ``*_mb``); other values unchanged."""
    if not _is_number(value):
        return value
    if name == "seconds" or name.endswith("_seconds"):
        return duration(value)
    if name.endswith("_bytes"):
        return size(value)
    if name.endswith("_mb"):
        return mebibytes(value)
    return value


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
    completed: int, total: int, elapsed: float | None, eta: float | None, detail: object = ""
) -> str:
    """``шаг 3/10 · 30 % · прошло: 4,2 секунды · осталось: ≈ 9,8 секунды · detail``."""
    parts = [tr("progress.step", completed=completed, total=total)]
    if total:
        parts.append(format_percent(100 * completed / total, 0))
    parts.append(tr("progress.elapsed", duration=format_duration(elapsed)))
    if eta is None:
        parts.append(tr("progress.eta_unknown"))
    else:
        parts.append(tr("progress.eta", duration=format_duration(eta)))
    text = str(detail)  # a Msg renders in the current language
    if text:
        parts.append(text)
    return " · ".join(parts)


def estimate_eta(completed: int, total: int, elapsed: float) -> float | None:
    if completed <= 0 or total <= completed:
        return 0.0 if total and completed >= total else None
    return elapsed / completed * (total - completed)
