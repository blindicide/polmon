"""Localized quantities: unit words agree with the number in Russian, symbols in English.

These tests pin the formatter's output (its contract is the text); everything else asserts on
identifiers. ``\\u00a0`` joins a number to its unit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from polmon.client import i18n
from polmon.client.errors import backend_message, limit_items
from polmon.client.formatting import (
    duration,
    format_bytes,
    format_duration,
    format_mebibytes,
    format_millicores,
    format_percent,
    mebibytes,
    quantity_for,
    size,
)
from polmon.client.i18n import Msg

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from i18n_audit import english_units  # noqa: E402

N = " "


@pytest.fixture
def russian():  # noqa: ANN201
    previous = i18n.language()
    i18n.set_language("ru")
    yield
    i18n.set_language(previous)


@pytest.fixture
def english():  # noqa: ANN201
    previous = i18n.language()
    i18n.set_language("en")
    yield
    i18n.set_language(previous)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0.25, f"250{N}миллисекунд"),
        (0.001, f"1{N}миллисекунда"),
        (0.002, f"2{N}миллисекунды"),
        (1, f"1{N}секунда"),
        (2, f"2{N}секунды"),
        (5, f"5{N}секунд"),
        (11, f"11{N}секунд"),
        (21, f"21{N}секунда"),
        (4.2, f"4,2{N}секунды"),  # a fraction takes the genitive singular
        (1.5, f"1,5{N}секунды"),
        (59.96, f"1{N}минута"),
        (300, f"5{N}минут"),  # the dashboard limit that read "5 min 00 s"
        (75, f"1{N}минута 15{N}секунд"),
        (122, f"2{N}минуты 2{N}секунды"),
        (3600, f"1{N}час"),
        (3700, f"1{N}час 1{N}минута"),
        (7200, f"2{N}часа"),
        (18000, f"5{N}часов"),
        (-1.5, f"−1,5{N}секунды"),
    ],
)
def test_russian_durations_use_words_that_agree_with_the_number(
    russian, seconds: float, text: str  # noqa: ANN001
) -> None:
    assert format_duration(seconds) == text
    assert english_units(text) == []


def test_compact_durations_skip_milliseconds(russian) -> None:  # noqa: ANN001
    assert format_duration(0.54, milliseconds=False) == f"0,5{N}секунды"
    assert format_duration(0.04, milliseconds=False) == f"0{N}секунд"
    assert format_duration(75, milliseconds=False) == format_duration(75)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0.25, f"250{N}ms"), (4.2, f"4.2{N}s"), (300, f"5{N}min"), (75, f"1{N}min 15{N}s"),
     (3700, f"1{N}h 1{N}min")],
)
def test_english_durations_keep_the_unit_symbols(english, seconds: float, text: str) -> None:  # noqa: ANN001
    assert format_duration(seconds) == text


def test_russian_sizes_and_other_units(russian) -> None:  # noqa: ANN001
    assert format_bytes(1536 * 1024) == f"1,5{N}МиБ"
    assert format_mebibytes(0.5) == f"0,5{N}МиБ"
    assert format_bytes(1) == f"1{N}байт"
    assert format_bytes(2) == f"2{N}байта"
    assert format_bytes(512) == f"512{N}байт"
    assert format_bytes(3 * 1_048_576) == f"3,0{N}МиБ"
    assert format_bytes(1536) == f"1,5{N}КиБ"
    assert format_bytes(5 * 1024**3) == f"5,0{N}ГиБ"
    assert format_mebibytes(512) == f"512{N}МиБ"
    assert format_mebibytes(12.5) == f"12,5{N}МиБ"
    assert format_millicores(1) == f"1{N}миллиядро"
    assert format_millicores(2) == f"2{N}миллиядра"
    assert format_millicores(250) == f"250{N}миллиядер"
    assert format_percent(12.5) == f"12,5{N}%"
    for missing in (format_duration, format_bytes, format_percent):
        assert missing(None) == "—"


def test_english_sizes_keep_the_unit_symbols(english) -> None:  # noqa: ANN001
    assert format_bytes(512) == f"512{N}B"
    assert format_bytes(3 * 1_048_576) == f"3.0{N}MiB"
    assert format_mebibytes(512) == f"512{N}MiB"
    assert format_millicores(250) == f"250{N}mCPU"
    assert format_percent(12.5) == f"12.5{N}%"


def test_quantities_follow_a_language_switch(russian) -> None:  # noqa: ANN001
    message = Msg("progress.elapsed", duration=duration(300))
    assert format_duration(300) in str(message)
    i18n.set_language("en")
    assert format_duration(300) == f"5{N}min"
    assert format_duration(300) in str(message)  # rendered again, in English
    assert str(size(2048)) == format_bytes(2048)


def test_backend_parameters_carry_their_unit(russian) -> None:  # noqa: ANN001
    assert quantity_for("seconds", 2.0) == duration(2.0)
    assert quantity_for("port_ready_seconds", 3) == duration(3)
    assert quantity_for("limit_bytes", 1024) == size(1024)
    assert quantity_for("limit_mb", 64) == mebibytes(64)
    assert quantity_for("count", 3) == 3
    assert quantity_for("seconds", "n/a") == "n/a"
    message = backend_message("hybrid.bridge_not_forwarding", {"bridge": "br0", "seconds": 2.0})
    assert isinstance(message, Msg) and message.params["seconds"] == duration(2.0)
    assert english_units(str(message)) == []


def test_admission_limits_show_values_with_units(russian) -> None:  # noqa: ANN001
    items = limit_items(
        {
            "duration_seconds": {"requested": 900, "limit": 300},
            "available_memory": {"required_mb_including_reserve": 900, "available_mb": 512},
            "memory_reserve_mb": {"requested": 64, "minimum": 256},
            "endpoint_count": {"projected": 300, "limit": 250},
        }
    )
    rendered = [str(item) for item in items]
    assert format_duration(900) in rendered[0] and format_duration(300) in rendered[0]
    assert format_mebibytes(900) in rendered[1] and format_mebibytes(512) in rendered[1]
    assert format_mebibytes(256) in rendered[2]
    assert "300" in rendered[3] and "МиБ" not in rendered[3]  # counts have no unit
    assert all(english_units(text) == [] for text in rendered)
