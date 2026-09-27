"""The Qt bundle filter keeps what the localized client needs and prunes the rest."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))

from qt_bundle import KEPT_TRANSLATIONS, keep  # noqa: E402

from polmon.client.locales import CATALOGS  # noqa: E402


def test_every_non_english_ui_language_keeps_its_qt_translation() -> None:
    assert {f"qtbase_{code}.qm" for code in CATALOGS if code != "en"} == KEPT_TRANSLATIONS


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_translations_are_pruned_to_the_ui_languages(os_name: str) -> None:
    root = "PySide6/Qt/translations" if os_name == "linux" else "PySide6\\translations"
    separator = "/" if os_name == "linux" else "\\"
    assert keep(f"{root}{separator}qtbase_ru.qm", os_name)
    for other in ("qtbase_de.qm", "qt_ru.qm", "qtdeclarative_ru.qm", "qtbase_en.qm"):
        assert not keep(f"{root}{separator}{other}", os_name)


def test_platform_plugins_are_kept_per_os() -> None:
    assert keep("PySide6/Qt/plugins/platforms/libqxcb.so", "linux")
    assert not keep("PySide6/Qt/plugins/platforms/libqvnc.so", "linux")
    assert keep("PySide6\\plugins\\platforms\\qwindows.dll", "windows")
    assert not keep("PySide6/Qt/plugins/imageformats/libqjpeg.so", "linux")
