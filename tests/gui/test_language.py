"""Russian by default, English at runtime: every screen switches in place and keeps its state.

Assertions use widget identifiers and machine values; display text is only inspected for the
*language* it is in (no Cyrillic in English, no untranslated English in Russian).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from conftest import connect, l0_topology, ping_scenario, wait_connected
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
)

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from i18n_audit import CYRILLIC, _latin_prose  # noqa: E402

from polmon.client import i18n  # noqa: E402
from polmon.client.errors import Problem  # noqa: E402
from polmon.client.locales import AUTONYMS  # noqa: E402
from polmon.client.widgets import JsonTree  # noqa: E402

LATIN_DATA = re.compile(r"^[\w.:/@+-]+$")  # identifiers, addresses, paths, versions
# A number followed by an English unit symbol: "5 min 00 s", "4.2 s", "512 MiB", "250 mCPU".
ENGLISH_UNIT_AFTER_NUMBER = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?[\s\u00a0]*"
    r"(ms|s|sec|min|h|B|KB|MB|GB|KiB|MiB|GiB|TiB|mCPU|bytes?)(?![\w-])"
)


def visible_texts(window) -> list[tuple[str, str]]:
    """(where, text) for every piece of interface text: chrome, headers, cells, menus."""
    texts: list[tuple[str, str]] = [("window title", window.windowTitle())]

    def add(widget, text: object) -> None:
        if isinstance(text, str) and text.strip():
            texts.append((widget.objectName() or type(widget).__name__, text))

    for widget in window.findChildren(QLabel):
        add(widget, re.sub(r"<[^>]*>|&[a-z]+;", " ", widget.text()))
        add(widget, widget.toolTip())
    for widget in window.findChildren(QAbstractButton):
        add(widget, widget.text())
        add(widget, widget.toolTip())
    for widget in window.findChildren(QGroupBox):
        add(widget, widget.title())
    for widget in window.findChildren(QLineEdit):
        add(widget, widget.placeholderText())
    for widget in window.findChildren(QAbstractSpinBox):
        add(widget, widget.text())  # value and unit suffix
        add(widget, widget.toolTip())
    for widget in window.findChildren(QComboBox):
        if not widget.isEditable():
            for index in range(widget.count()):
                add(widget, widget.itemText(index))
    for widget in window.findChildren(QTabWidget):
        for index in range(widget.count()):
            add(widget, widget.tabText(index))
    for widget in window.findChildren(QAbstractItemView):
        model = widget.model()
        try:
            columns = model.columnCount(QModelIndex())
        except TypeError:  # list models (completers, combo popups) have no header
            columns = 0
        for column in range(columns):
            add(widget, model.headerData(column, Qt.Orientation.Horizontal))
        if isinstance(widget, QTableWidget):
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is not None:
                        add(widget, item.text())
                        add(widget, item.toolTip())
        if isinstance(widget, QTreeWidget) and not isinstance(widget, JsonTree):
            for index in range(widget.topLevelItemCount()):
                item = widget.topLevelItem(index)
                add(widget, " ".join(item.text(c) for c in range(widget.columnCount())))
    for menu in window.findChildren(QMenu):
        add(menu, menu.title())
        for action in menu.actions():
            add(menu, action.text().replace("&", ""))
    for widget in window.findChildren(QTextEdit) + window.findChildren(QPlainTextEdit):
        add(widget, widget.accessibleName())  # contents are documents or the history log
    add(window.statusBar(), window.statusBar().currentMessage())
    return texts


def english_leftovers(window) -> list[tuple[str, str]]:
    return [
        (where, text)
        for where, text in visible_texts(window)
        if not LATIN_DATA.match(text.strip())
        and not text.lstrip().startswith(("{", "["))  # a JSON value shown verbatim
        and _latin_prose(text)
    ]


def unit_leftovers(window, *documents: str) -> list[tuple[str, str]]:
    """English unit symbols after a number anywhere in the interface, the activity log and the
    given rendered documents (a Russian report)."""
    texts = visible_texts(window) + [("activity log", window.log_view.toPlainText())]
    texts += [("document", document) for document in documents]
    return [
        (where, match.group(0))
        for where, text in texts
        for match in ENGLISH_UNIT_AFTER_NUMBER.finditer(text)
    ]


def cyrillic_leftovers(window) -> list[tuple[str, str]]:
    """Cyrillic text in English mode (language names are shown as autonyms on purpose)."""
    return [
        (where, text)
        for where, text in visible_texts(window)
        if CYRILLIC.search(text) and text not in AUTONYMS.values()
    ]


def walk_all_pages(window, qtbot) -> None:
    for key in window.pages:
        window.navigate(key)
        qtbot.wait(20)


def test_russian_is_the_default_language(window, monkeypatch) -> None:
    from polmon.client.locales import DEFAULT_LANGUAGE

    monkeypatch.delenv(i18n.LANGUAGE_ENVIRONMENT_VARIABLE, raising=False)
    assert DEFAULT_LANGUAGE == "ru"
    assert i18n.initial_language() == "ru"  # nothing stored, no override
    assert i18n.initial_language("en") == "en"  # the operator's stored choice wins
    assert window.language_actions[i18n.language()].isChecked()


def test_runtime_switch_retranslates_every_screen_and_keeps_state(
    window, qtbot, live_backend, tmp_path
) -> None:
    window.set_language("ru")
    topology = tmp_path / "l0-small.yml"
    topology.write_text(l0_topology(), encoding="utf-8")
    scenario = tmp_path / "ping.yml"
    scenario.write_text(ping_scenario(actions=2), encoding="utf-8")
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    topologies = window.pages["topologies"]
    window.navigate("topologies", topology)
    qtbot.waitUntil(lambda: topologies.badge.status == "valid", timeout=10_000)
    topologies.deploy()
    deployment = window.pages["deployment"]
    qtbot.waitUntil(lambda: deployment.table.rowCount() == 1, timeout=20_000)
    qtbot.waitUntil(lambda: not window.context.busy, timeout=20_000)
    scenarios = window.pages["scenarios"]
    window.navigate("scenarios", scenario)
    qtbot.waitUntil(scenarios.ready, timeout=10_000)
    scenarios.run()
    qtbot.waitUntil(lambda: scenarios.outcome.status == "succeeded", timeout=30_000)
    scenarios.report_button.click()
    reports = window.pages["reports"]
    qtbot.waitUntil(lambda: reports.report is not None, timeout=10_000)
    walk_all_pages(window, qtbot)
    leftovers = english_leftovers(window)
    assert leftovers == [], "\n".join(map(repr, leftovers))
    units = unit_leftovers(window, reports.rendered.toPlainText())
    assert units == [], units

    state = (
        window.session.state,
        window.bar.url.text(),
        topologies.editor.toPlainText(),
        scenarios.editor.toPlainText(),
        deployment.table.rowCount(),
        scenarios.sequence.rowCount(),
        reports.report["experiment_id"],
    )
    window.navigate("reports")
    window.set_language("en")
    assert i18n.language() == "en"
    assert window.current_page.key == "reports"  # the operator stays where they were
    walk_all_pages(window, qtbot)
    leftovers = cyrillic_leftovers(window)
    assert leftovers == [], "\n".join(map(repr, leftovers))
    assert "Traceback" not in window.log_view.toPlainText()
    log = [
        line
        for line in window.log_view.toPlainText().splitlines()
        if CYRILLIC.search(line) and not any(name in line for name in AUTONYMS.values())
    ]
    assert log == [], log  # the activity log is re-rendered in English too
    assert (
        window.session.state,
        window.bar.url.text(),
        topologies.editor.toPlainText(),
        scenarios.editor.toPlainText(),
        deployment.table.rowCount(),
        scenarios.sequence.rowCount(),
        reports.report["experiment_id"],
    ) == state
    assert CYRILLIC.search(reports.rendered.toPlainText()) is None  # the report re-renders

    window.toggle_language()  # Ctrl+Shift+U
    assert i18n.language() == "ru"
    walk_all_pages(window, qtbot)
    leftovers = english_leftovers(window)
    assert leftovers == [], "\n".join(map(repr, leftovers))
    units = unit_leftovers(window, reports.rendered.toPlainText())
    assert units == [], units  # values rendered in English came back in Russian
    assert i18n.missing == set()


def test_russian_ui_shows_no_english_units(window, qtbot, live_backend, tmp_path) -> None:
    """Durations, sizes and CPU shares read in Russian words on every screen (dashboard limits
    and tiles, estimates, deployment times, spin boxes, tooltips, the log) — also after English
    was shown in between."""
    window.set_language("ru")
    topology = tmp_path / "l0-small.yml"
    topology.write_text(l0_topology(), encoding="utf-8")
    connect(qtbot, window, live_backend)
    wait_connected(qtbot, window)
    topologies = window.pages["topologies"]
    window.navigate("topologies", topology)
    qtbot.waitUntil(lambda: topologies.badge.status == "valid", timeout=10_000)
    topologies.deploy()
    deployment = window.pages["deployment"]
    qtbot.waitUntil(lambda: deployment.table.rowCount() == 1, timeout=20_000)
    qtbot.waitUntil(lambda: not window.context.busy, timeout=20_000)
    window.set_language("en")
    window.set_language("ru")
    walk_all_pages(window, qtbot)
    units = unit_leftovers(window)
    assert units == [], "\n".join(map(repr, units))
    for key, page in window.pages.items():  # words are longer than symbols: still no scrolling
        needed = window.minimum_size_for(page)
        assert needed.width() <= 1440 and needed.height() <= 900, (key, needed)

    from polmon.client.formatting import format_duration, format_mebibytes

    limits = window.pages["dashboard"].limits.values
    duration = limits["limit.max_experiment_duration_seconds"]
    assert duration.text().endswith(format_duration(duration.property("raw")))
    reserve = limits["limit.memory_safety_threshold_mb"]
    assert reserve.text().endswith(format_mebibytes(reserve.property("raw")))
    timeout = window.bar.timeout
    assert timeout.suffix().strip() == i18n.tr_n("unit.second", timeout.value())
    timeout.setValue(1)
    assert timeout.suffix().strip() == i18n.tr_n("unit.second", 1)  # agrees with the value
    idle = window.pages["benchmarks"].idle  # one decimal shown: "0,5 секунды", "1,0 секунды"
    for value in (0.5, 1.0):
        idle.setValue(value)
        assert idle.suffix().strip() == i18n.tr_n("unit.second", 0.5), value
    assert i18n.missing == set()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_window_fits_1440_by_900_on_every_page_with_banners(window, qtbot, language) -> None:
    """At 1440x900 no page scrolls or clips, with a problem banner shown; on a smaller screen the
    window still fits and the page area scrolls."""
    window.set_language(language)
    problem = Problem("problem.l0_only", i18n.Msg("backend.fidelity.l0_only"))
    for page in window.pages.values():
        page.banner.show_problem(problem)
    window.resize(1440, 900)
    qtbot.wait(20)
    for key, page in window.pages.items():
        window.navigate(key)
        qtbot.wait(10)
        needed = window.minimum_size_for(page)
        assert needed.width() <= 1440 and needed.height() <= 900, (language, key, needed)
        if (window.width(), window.height()) == (1440, 900):  # a smaller screen clamps it
            scroll = window.page_scrolls[key]
            bars = scroll.horizontalScrollBar(), scroll.verticalScrollBar()
            assert not any(bar.isVisible() for bar in bars), (language, key)
    for mode in ("remote", "local"):  # a 1366x768 laptop shows the window; its pages scroll
        window.bar.mode.setCurrentIndex(window.bar.mode.findData(mode))
        qtbot.wait(10)
        minimum = window.minimumSizeHint()
        assert minimum.width() <= 1366 and minimum.height() <= 768, (language, mode, minimum)
