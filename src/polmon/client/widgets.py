"""Reusable, theme- and language-aware widgets for a dense operator console (docs/UI-GUIDE.md).

Every visible string is bound to a catalog key (``polmon.client.i18n``), so a language switch
re-renders it in place. Components: role-styled buttons, cards, sortable tables with monospaced
identifier columns, status badges that pair colour with a glyph and a word, counter tiles, the
problem banner, empty/loading/error state views with a spinner, and the YAML editor.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable, Sequence

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPainterPath,
    QPen,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from polmon.client import i18n, theme
from polmon.client.errors import Problem
from polmon.client.formatting import progress_text
from polmon.client.i18n import Msg, bind, bind_fn, bind_text, bind_tip, status_label, tr
from polmon.client.tasks import ProgressUpdate, TaskHandle

# Item data role holding a cell's machine value (raw status, identifier, number) for tests and
# for behaviour that must not depend on the display language.
RAW_ROLE = Qt.ItemDataRole.UserRole + 1


class ThemeAware:
    """Mixin: re-run ``restyle`` when the application palette changes (theme switch)."""

    _restyling = False

    def restyle(self) -> None:  # pragma: no cover - overridden
        pass

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        palette_events = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
        if event.type() in palette_events and not self._restyling:
            self._restyling = True
            try:
                self.restyle()
            finally:
                self._restyling = False
        super().changeEvent(event)  # type: ignore[misc]


def monospace_font() -> QFont:
    """The identifier font (theme.MONOSPACE_FAMILIES) at the UI's text size."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)  # keeps its size
    font.setFamily(theme.monospace_family())
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


# -- labels and buttons -----------------------------------------------------------------------


def label(
    key: str | Msg | None = None, *, name: str | None = None, wrap: bool = False, **params: object
) -> QLabel:
    widget = QLabel()
    if name:
        widget.setObjectName(name)
    if key is not None:
        bind_text(widget, key, **params)
    widget.setWordWrap(wrap)
    return widget


def muted(key: str | Msg | None = None, **params: object) -> QLabel:
    return label(key, name="muted", wrap=True, **params)


def accessible(widget: QWidget, key: str) -> QWidget:
    """A localized accessible name (screen readers) the window's automatic naming keeps."""
    widget.setProperty("namedByPage", True)
    bind(widget, "setAccessibleName", key)
    return widget


def page_title(key: str) -> QLabel:
    return label(key, name="pageTitle")


def section_label(key: str) -> QLabel:
    return label(key, name="sectionLabel")


def button(
    key: str | Msg,
    role: str = "secondary",
    *,
    tip: str | Msg | None = None,
    name: str | None = None,
    **params: object,
) -> QPushButton:
    """A push button whose look follows its role: primary, secondary, danger or quiet."""
    widget = QPushButton()
    widget.setProperty("role", role)
    if name:
        widget.setObjectName(name)
    bind_text(widget, key, **params)
    if tip is not None:
        bind_tip(widget, tip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def primary_button(key: str | Msg, **kwargs: object) -> QPushButton:
    return button(key, "primary", **kwargs)  # type: ignore[arg-type]


def danger_button(key: str | Msg, **kwargs: object) -> QPushButton:
    return button(key, "danger", **kwargs)  # type: ignore[arg-type]


# -- cards ------------------------------------------------------------------------------------


class Card(QFrame):
    """A titled panel: header (title, hint, actions on the right) above a body layout."""

    def __init__(
        self,
        title: str | None = None,
        *,
        hint: str | None = None,
        name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        if name:
            self.setProperty("cardName", name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE["md"], theme.SPACE["md"] - 2, theme.SPACE["md"],
                                 theme.SPACE["md"])
        outer.setSpacing(theme.SPACE["sm"])
        self.header = QHBoxLayout()
        self.header.setSpacing(theme.SPACE["sm"])
        self.title = label(title, name="cardTitle") if title else None
        if self.title is not None:
            self.header.addWidget(self.title)
        self.hint = label(hint, name="cardHint", wrap=True) if hint else None
        if self.hint is not None:
            self.header.addWidget(self.hint)
        self.header.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(theme.SPACE["sm"])
        self.header.addLayout(self.actions)
        if title or hint:
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.SPACE["sm"])
        outer.addLayout(self.body, 1)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget


class KeyValueGrid(QWidget):
    """Dense label/value pairs in ``columns`` column pairs (limits, identity, summaries)."""

    def __init__(
        self, keys: Sequence[str], *, columns: int = 2, wrap_values: bool = False, parent=None  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE["lg"])
        grid.setVerticalSpacing(theme.SPACE["xs"] + 2)
        self.values: dict[str, QLabel] = {}
        rows = (len(keys) + columns - 1) // columns
        for index, key in enumerate(keys):
            row, column = index % rows, (index // rows) * 2
            name = label(key, name="muted")
            value = QLabel("—")
            value.setWordWrap(wrap_values)
            value.setObjectName("kvValue")
            value.setProperty("kvKey", key)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, row, column)
            grid.addWidget(value, row, column + 1)
            self.values[key] = value
        for column in range(columns):
            grid.setColumnStretch(column * 2 + 1, 1)

    def set(self, key: str, value: object, *, tone: str = "", mono: bool = False) -> None:
        widget = self.values[key]
        # A no-break space keeps the glyph with its word when the value wraps.
        glyph = f"{theme.STATUS_GLYPHS[tone]}\u00a0" if tone in theme.STATUS_GLYPHS else ""
        widget.setText(f"{glyph}{cell_text(value)}")
        widget.setProperty("raw", value if isinstance(value, str | int | float) else None)
        widget.setFont(monospace_font() if mono else self.font())
        if mono:  # identifiers (URLs, IDs) never break mid-token
            widget.setWordWrap(False)
        widget.setStyleSheet(f"color: {theme.hex_color(tone)}; font-weight: 600;" if tone else "")


# -- tables -----------------------------------------------------------------------------------


def make_table(
    headers: Sequence[str],
    *,
    stretch: int | None = None,
    mono: Iterable[int] = (),
    sortable: bool = True,
    name: str | None = None,
) -> QTableWidget:
    """A dense, sortable, resizable table; ``headers`` are catalog keys, ``mono`` columns hold
    identifiers (URLs, IDs, addresses, names) and render monospaced."""
    table = QTableWidget(0, len(headers))
    if name:
        table.setObjectName(name)
    table.header_keys = tuple(headers)  # type: ignore[attr-defined]
    table.mono_columns = frozenset(mono)  # type: ignore[attr-defined]
    table.setProperty("sortable", sortable)
    bind_fn(
        table,
        lambda widget: widget.setHorizontalHeaderLabels(
            [tr(key) if key else "" for key in widget.header_keys]
        ),
        tag="headers",
    )
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(26)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionsMovable(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(stretch is None)
    header.setMinimumSectionSize(48)
    # The stylesheet draws section labels in the caption type; size hints must use the same font
    # or every column is sized for text larger than the one shown.
    caption = QFont(header.font())
    caption.setPixelSize(theme.TYPE["caption"])
    caption.setWeight(QFont.Weight.DemiBold)
    header.setFont(caption)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    table.setSortingEnabled(sortable)
    table.viewport().installEventFilter(_TrimOnResize(table))
    return table


def cell_text(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return tr("common.yes") if value else tr("common.no")
    if isinstance(value, Msg):
        return str(value)
    return str(value)


class _Item(QTableWidgetItem):
    """Sorts numbers numerically and everything else case-insensitively."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        left, right = self.data(RAW_ROLE), other.data(RAW_ROLE)
        if isinstance(left, int | float) and isinstance(right, int | float):
            return left < right
        return self.text().casefold() < other.text().casefold()


def fill_table(
    table: QTableWidget,
    rows: Iterable[Sequence[object]],
    *,
    colors: dict[int, str] | None = None,
    data: Sequence[object] | None = None,
) -> None:
    """Replace all rows. ``colors`` marks status columns: their machine value is shown as a
    localized word with a glyph and tinted by tone; the raw value stays in ``RAW_ROLE``."""
    rows = list(rows)
    sortable = bool(table.property("sortable"))
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    mono = getattr(table, "mono_columns", frozenset())
    font = monospace_font() if mono else None
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            status = colors is not None and column in colors and value not in (None, "")
            text = f"{theme.status_glyph(str(value))} {status_label(value)}" if status else (
                cell_text(value)
            )
            item = _Item(text)
            # Messages keep their catalog key as the machine value (identifier-based tests).
            item.setData(RAW_ROLE, value.key if isinstance(value, Msg) else value)
            item.setToolTip(text if len(text) > 40 else "")
            if status:
                item.setForeground(theme.color(theme.status_color(str(value))))
            if font is not None and column in mono:
                item.setFont(font)
            if isinstance(value, int | float) and not isinstance(value, bool):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if data is not None and column == 0:
                item.setData(Qt.ItemDataRole.UserRole, data[row_index])
            table.setItem(row_index, column, item)
    if sortable:
        table.setSortingEnabled(True)
    fit_columns(table)


def fit_columns(table: QTableWidget) -> None:
    """Size interactive columns to their content once, capped so one long cell cannot hog."""
    header = table.horizontalHeader()
    metrics = header.fontMetrics()  # the caption font the stylesheet draws labels in
    padding = 2 * theme.SPACE["sm"] + 2
    sorted_column = header.sortIndicatorSection() if table.isSortingEnabled() else -1
    natural: dict[int, int] = {}
    content: dict[int, int] = {}
    for column in range(table.columnCount()):
        if header.sectionResizeMode(column) != QHeaderView.ResizeMode.Interactive:
            continue
        # Qt's own header hint reserves sort-indicator room in every section; only the sorted
        # column shows one.
        item = table.horizontalHeaderItem(column)
        label = metrics.horizontalAdvance(item.text() if item else "") + padding
        if column == sorted_column:
            label += 16
        content[column] = min(table.sizeHintForColumn(column) + 2, 360)
        natural[column] = min(max(label, content[column]), 360)
    table.natural_widths = natural  # type: ignore[attr-defined]
    table.content_widths = content  # type: ignore[attr-defined]
    _fit_to_view(table)


def _fit_to_view(table: QTableWidget) -> None:
    """Apply the natural column widths; when the table is wider than its view, the overflow is
    taken from header slack (a label wider than the cells below it), never from cell content —
    beyond that the table scrolls. Runs after filling and on every resize of the view, always
    from the natural widths (tables are often filled while hidden, before their final width is
    known)."""
    natural: dict[int, int] = getattr(table, "natural_widths", {})
    content: dict[int, int] = getattr(table, "content_widths", {})
    available = table.viewport().width()
    if not natural or available <= 0:
        return
    header = table.horizontalHeader()
    visible = {column: width for column, width in natural.items()
               if not table.isColumnHidden(column)}
    stretched = sum(
        header.minimumSectionSize()
        for column in range(table.columnCount())
        if header.sectionResizeMode(column) == QHeaderView.ResizeMode.Stretch
    )
    overflow = sum(visible.values()) + stretched - available
    slack = {column: max(width - max(content.get(column, width), 48), 0)
             for column, width in visible.items()}
    total = sum(slack.values())
    take = min(max(overflow, 0), total)
    for column, width in visible.items():
        if take and slack[column]:
            width -= min(slack[column], -(-take * slack[column] // total))  # proportional
        header.resizeSection(column, width)


class _TrimOnResize(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize:
            _fit_to_view(self.parent())  # type: ignore[arg-type]
        return False


def raw_value(table: QTableWidget, row: int, column: int) -> object:
    item = table.item(row, column)
    return None if item is None else item.data(RAW_ROLE)


# -- status -----------------------------------------------------------------------------------


class StatusBadge(ThemeAware, QLabel):
    """A pill such as ✓ УСПЕШНО / ✕ ОШИБКА: glyph, word and tone, never colour alone."""

    def __init__(self, status: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status = ""
        self.set_status(status)
        bind_fn(self, lambda badge: badge.set_status(badge.status), tag="status")

    def set_status(self, status: str) -> None:
        self._status = status
        self.setProperty("status", status)
        self.setText(
            f"{theme.status_glyph(status)}  {status_label(status).upper()}" if status else ""
        )
        self.setVisible(bool(status))
        self.restyle()

    @property
    def status(self) -> str:
        return self._status

    def restyle(self) -> None:
        tone = theme.status_color(self._status or "")
        foreground = theme.hex_color(tone if tone != "muted" else "text_muted")
        background = theme.hex_color(f"{tone}_soft") if tone != "muted" else theme.hex_color(
            "surface_alt"
        )
        self.setStyleSheet(
            f"QLabel {{ color: {foreground}; background: {background}; border-radius: 10px;"
            f" padding: 2px 10px; font-weight: 700; font-size: {theme.TYPE['caption']}px; }}"
        )


class Led(ThemeAware, QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._tone = "muted"
        self.restyle()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.restyle()

    def restyle(self) -> None:
        self.setStyleSheet(
            f"QLabel {{ background: {theme.hex_color(self._tone)}; border-radius: 5px; }}"
        )


class ProblemBanner(ThemeAware, QFrame):
    """Inline, dismissible explanation of the last failure (never a modal stall)."""

    GLYPHS = {"danger": "✕", "warning": "!", "info": "i", "success": "✓"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("problemBanner")
        self._severity = "danger"
        self.problem: Problem | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE["md"], theme.SPACE["sm"], theme.SPACE["sm"],
                                  theme.SPACE["sm"])
        layout.setSpacing(theme.SPACE["sm"])
        self.glyph = QLabel()
        self.glyph.setFixedWidth(18)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        close = QToolButton()
        close.setObjectName("bannerClose")
        close.setText("✕")
        close.setAutoRaise(True)
        bind_tip(close, "common.dismiss")
        close.clicked.connect(self.clear)
        layout.addWidget(self.glyph)
        layout.addWidget(self.label, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()
        i18n.on_language_changed(self, "render")

    def show_problem(self, problem: Problem, severity: str = "danger") -> None:
        self.problem = problem
        self._severity = severity
        self.render()
        self.restyle()
        self.show()

    def show_message(self, title: str | Msg, detail: str | Msg, severity: str = "info") -> None:
        self.show_problem(Problem.message(title, detail), severity)

    def render(self) -> None:
        problem = self.problem
        if problem is None:
            return
        items = "".join(f"<li>{_escape(item)}</li>" for item in problem.items)
        hint = f"<div style='margin-top:2px'>{_escape(problem.hint)}</div>" if problem.hint else ""
        self.label.setText(
            f"<b>{_escape(problem.title)}</b> — {_escape(problem.detail)}"
            + (f"<ul style='margin:2px 0 2px -20px'>{items}</ul>" if items else "")
            + hint
        )

    def clear(self) -> None:
        self.problem = None
        self.hide()

    def restyle(self) -> None:
        tone = theme.hex_color(self._severity)
        background = theme.hex_color(f"{self._severity}_soft")
        self.glyph.setText(self.GLYPHS.get(self._severity, "!"))
        self.glyph.setStyleSheet(f"color: {tone}; font-weight: 700;")
        self.setStyleSheet(
            f"QFrame#problemBanner {{ background: {background}; border: 1px solid {tone};"
            " border-radius: 8px; }"
        )


def _escape(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -- counters ---------------------------------------------------------------------------------


class Sparkline(QWidget):
    """Minimal line chart of the last ``capacity`` samples (QPainter; no chart library)."""

    def __init__(self, capacity: int = 120, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.samples: deque[float] = deque(maxlen=capacity)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(120, 26)

    def add(self, value: float | None) -> None:
        if value is not None:
            self.samples.append(float(value))
            self.update()

    def clear(self) -> None:
        self.samples.clear()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt override
        if len(self.samples) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(1, 2, -1, -2)
        low, high = min(self.samples), max(self.samples)
        span = (high - low) or 1.0
        slots = max(len(self.samples), min(30, self.samples.maxlen or 30))
        step = area.width() / (slots - 1)
        offset = area.width() - step * (len(self.samples) - 1)
        path = QPainterPath()
        for index, value in enumerate(self.samples):
            x = area.left() + offset + index * step
            y = area.bottom() - (value - low) / span * area.height()
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(area.right(), area.bottom())
        fill.lineTo(area.left() + offset, area.bottom())
        fill.closeSubpath()
        tint = theme.color("chart")
        tint.setAlpha(46)
        painter.fillPath(fill, tint)
        painter.setPen(QPen(theme.color("chart"), 1.5))
        painter.drawPath(path)


class CounterTile(QFrame):
    """Caption, big value, secondary line and an optional sparkline."""

    def __init__(
        self, caption: str, *, sparkline: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tile")
        self.caption_key = caption
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE["md"], theme.SPACE["sm"], theme.SPACE["md"],
                                  theme.SPACE["sm"])
        layout.setSpacing(2)
        self.caption = label(caption, name="tileCaption")
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        self.secondary = QLabel("")
        self.secondary.setObjectName("tileSecondary")
        self.secondary.setWordWrap(True)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.secondary)
        self.sparkline = Sparkline() if sparkline else None
        if self.sparkline is not None:
            layout.addWidget(self.sparkline)
        layout.addStretch(1)
        self.setMinimumWidth(140)

    def set(
        self, value: str, secondary: str = "", sample: float | None = None, tone: str = ""
    ) -> None:
        """Show a value; ``tone`` (``warning``/``danger``) tints it and adds a glyph."""
        glyph = f"{theme.STATUS_GLYPHS[tone]} " if tone in {"warning", "danger"} else ""
        self.value.setText(f"{glyph}{value}")
        self.value.setProperty("tone", tone)
        self.value.setStyleSheet(f"color: {theme.hex_color(tone)};" if tone else "")
        self.secondary.setText(secondary)
        if self.sparkline is not None:
            self.sparkline.add(sample)


# -- busy, empty, loading and error states ----------------------------------------------------


class Spinner(ThemeAware, QWidget):
    """An indeterminate arc for anything that takes more than a moment."""

    def __init__(self, size: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def spinning(self) -> bool:
        return self._timer.isActive()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme.color("accent"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        area = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(area, -self._angle * 16, 270 * 16)

    def restyle(self) -> None:
        self.update()


class StateView(QStackedWidget):
    """Shows ``content`` or a centred empty, loading or error message in its place."""

    CONTENT, MESSAGE = 0, 1

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stateView")
        self.content = content
        self.addWidget(content)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(theme.SPACE["sm"])
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner = Spinner(18)
        self.glyph = QLabel()
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.spinner)
        row.addWidget(self.glyph)
        row.addWidget(self.title)
        self.text = QLabel()
        self.text.setObjectName("muted")
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setMaximumWidth(520)
        layout.addLayout(row)
        layout.addWidget(self.text, 0, Qt.AlignmentFlag.AlignCenter)
        self.addWidget(panel)
        self.state = "content"
        self._title: Msg | str = ""
        self._detail: Msg | str = ""
        i18n.on_language_changed(self, "render")

    def show_content(self) -> None:
        self.state = "content"
        self.spinner.stop()
        self.setCurrentIndex(self.CONTENT)

    def show_empty(self, title: Msg | str, detail: Msg | str = "") -> None:
        self._show("empty", title, detail)

    def show_loading(self, title: Msg | str, detail: Msg | str = "") -> None:
        self._show("loading", title, detail)

    def show_error(self, title: Msg | str, detail: Msg | str = "") -> None:
        self._show("error", title, detail)

    def _show(self, state: str, title: Msg | str, detail: Msg | str) -> None:
        self.state = state
        self._title, self._detail = title, detail
        self.render()
        self.setCurrentIndex(self.MESSAGE)

    def render(self) -> None:
        self.title.setText(str(self._title))  # also while hidden: no stale language
        self.text.setText(str(self._detail))
        # A short title stays on one line; only a long one (or a narrow view) wraps.
        width = self.title.fontMetrics().horizontalAdvance(self.title.text()) + 4
        self.title.setMinimumWidth(min(width, 320))
        if self.state == "content":
            return
        loading = self.state == "loading"
        self.spinner.setVisible(loading)
        if loading:
            self.spinner.start()
        else:
            self.spinner.stop()
        glyphs = {"empty": ("○", "text_muted"), "error": ("✕", "danger")}
        glyph, tone = glyphs.get(self.state, ("", "text_muted"))
        self.glyph.setVisible(bool(glyph))
        self.glyph.setText(glyph)
        self.glyph.setStyleSheet(f"color: {theme.hex_color(tone)}; font-size: 15px;")
        self.text.setVisible(bool(str(self._detail)))


class OperationProgress(QWidget):
    """Status-bar progress for the current long operation: percent, step, elapsed, ETA, Cancel."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("operationProgress")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["sm"])
        self.spinner = Spinner(14)
        self.title = QLabel()
        self.title.setObjectName("fieldLabel")
        self.bar = QProgressBar()
        self.bar.setFixedWidth(160)
        self.bar.setTextVisible(True)
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.cancel = button("common.cancel", "quiet", tip="progress.cancel_tip", name="cancelOp")
        self.cancel.clicked.connect(self.cancel_requested)
        for widget in (self.spinner, self.title, self.bar, self.detail, self.cancel):
            layout.addWidget(widget)
        self.handle: TaskHandle | None = None
        self.update_: ProgressUpdate | None = None
        self._title: Msg | str = ""
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._render)
        self.hide()
        i18n.on_language_changed(self, "_render")

    def track(self, handle: TaskHandle, title: Msg | str, *, cancellable: bool = True) -> None:
        self.handle = handle
        self.update_ = None
        self._title = title
        self.cancel.setVisible(cancellable)
        self.bar.setRange(0, 0)  # busy until the first progress report
        handle.progress.connect(self._progress)
        handle.finished.connect(lambda: self._finished(handle))
        self.spinner.start()
        self.timer.start()
        self._render()
        self.show()

    def _progress(self, update: ProgressUpdate) -> None:
        self.update_ = update
        self._render()

    def _render(self) -> None:
        if self.handle is None:
            return
        self.title.setText(str(self._title))
        update = self.update_
        elapsed = self.handle.elapsed
        if update is None or not update.total:
            self.bar.setRange(0, 0)
            self.detail.setText(tr("progress.elapsed_only", seconds=f"{elapsed:.1f}"))
            return
        self.bar.setRange(0, update.total)
        self.bar.setValue(update.completed)
        self.bar.setFormat(f"{update.percent:.0f} %")
        self.detail.setText(
            progress_text(update.completed, update.total, elapsed, update.eta, update.detail)
        )

    def _finished(self, handle: TaskHandle) -> None:
        if handle is self.handle:
            self.handle = None
            self.timer.stop()
            self.spinner.stop()
            self.hide()
            self.title.clear()
            self.detail.clear()


class ActivityIndicator(QWidget):
    """Status-bar spinner for background work (validation, listings, reports) that outlasts
    ``delay_ms``; quick requests never flicker it."""

    def __init__(self, delay_ms: int = 400, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("activityIndicator")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE["xs"] + 2)
        self.spinner = Spinner(12)
        self.text = QLabel()
        self.text.setObjectName("muted")
        layout.addWidget(self.spinner)
        layout.addWidget(self.text)
        self._pending: dict[int, Msg | str] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._render)
        self.hide()
        i18n.on_language_changed(self, "_render")

    def begin(self, key: int, name: Msg | str) -> None:
        self._pending[key] = name
        if not self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def end(self, key: int) -> None:
        self._pending.pop(key, None)
        if not self._pending:
            self._timer.stop()
            self.spinner.stop()
            self.hide()
            self.text.clear()
        elif self.isVisible():
            self._render()

    def _render(self) -> None:
        if not self._pending:
            return
        names = list(self._pending.values())
        extra = f" (+{len(names) - 1})" if len(names) > 1 else ""
        self.text.setText(tr("activity.working", name=str(names[-1])) + extra)
        self.spinner.start()
        self.show()


# Tests (and scripted screenshots) answer confirmations through this hook instead of a modal.
_confirm_handler = None


def set_confirm_handler(handler) -> None:  # noqa: ANN001 - Callable[[str, str], bool] | None
    global _confirm_handler
    _confirm_handler = handler


def confirm(
    parent: QWidget,
    title: str,
    text: str | Msg,
    accept: str,
    *,
    destructive: bool = True,
    **params: object,
) -> bool:
    """Ask before an irreversible action; the accept button names the action and the default is
    the safe choice (Esc/Enter cancel)."""
    if _confirm_handler is not None:
        return bool(_confirm_handler(title, str(text)))
    box = QMessageBox(parent)
    box.setObjectName("confirmDialog")
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setWindowTitle(tr(title))
    box.setText(str(text))
    ok = box.addButton(tr(accept, **params), QMessageBox.ButtonRole.AcceptRole)
    ok.setObjectName("confirmAccept")
    ok.setProperty("role", "danger" if destructive else "primary")
    cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    cancel.setObjectName("confirmCancel")
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is ok


# -- YAML editor and JSON tree ----------------------------------------------------------------


class YamlHighlighter(QSyntaxHighlighter):
    """Minimal, fast YAML colouring: keys, comments, strings, scalars, list markers."""

    RULES = (
        (re.compile(r"^\s*-\s"), "muted"),
        (re.compile(r"^\s*(?:-\s+)?([A-Za-z_][\w-]*)(?=\s*:)"), "accent"),
        (re.compile(r"(?<=:\s)(?:true|false|null|~|-?\d+(?:\.\d+)?)(?=\s*(?:#|$))"), "warning"),
        (re.compile(r"\"[^\"]*\"|'[^']*'"), "success"),
        (re.compile(r"(?:^|\s)#.*$"), "muted"),
    )

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        for pattern, tone in self.RULES:
            fmt = QTextCharFormat()
            fmt.setForeground(theme.color(tone))
            if tone == "accent":
                fmt.setFontWeight(QFont.Weight.DemiBold)
            for match in pattern.finditer(text):
                group = 1 if match.lastindex else 0
                start, end = match.span(group)
                if start >= 0:
                    self.setFormat(start, end - start, fmt)


class _LineNumbers(QWidget):
    def __init__(self, editor: YamlEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt override
        self.editor.paint_gutter(event)


class YamlEditor(QPlainTextEdit):
    """Monospace YAML editor with line numbers and error-line highlighting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("yaml")
        self.setFont(monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(False)
        bind(self, "setPlaceholderText", "editor.placeholder")
        self._gutter = _LineNumbers(self)
        self._error_line: int | None = None
        self.highlighter = YamlHighlighter(self.document())
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._scroll_gutter)
        self._update_margins()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.highlighter.rehighlight()

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001 - Qt override
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._gutter.setGeometry(
            QRect(contents.left(), contents.top(), self.gutter_width(), contents.height())
        )

    def paint_gutter(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), theme.color("surface_alt"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_error = self._error_line == number + 1
                painter.setPen(theme.color("danger" if is_error else "muted"))
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 6,
                    height,
                    Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def set_error_line(self, line: int | None) -> None:
        """Highlight one line (one-based) as the location of a validation error."""
        self._error_line = line
        selections = []
        if line is not None and 0 < line <= self.blockCount():
            selection = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            tint = QColor(theme.hex_color("danger"))
            tint.setAlpha(45)
            fmt.setBackground(tint)
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.format = fmt
            cursor = QTextCursor(self.document().findBlockByNumber(line - 1))
            selection.cursor = cursor
            selections.append(selection)
        self.setExtraSelections(selections)
        self._gutter.update()

    def goto_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()


class JsonTree(QTreeWidget):
    """Expandable view of a JSON document (keys, values, types)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        bind_fn(
            self,
            lambda tree: tree.setHeaderLabels([tr("json.key"), tr("json.value")]),
            tag="headers",
        )
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(True)
        self._document: object = None
        self._depth = 1
        i18n.on_language_changed(self, "_reload")

    def load(self, document: object, *, expand_depth: int = 1) -> None:
        self._document, self._depth = document, expand_depth
        self._reload()

    def clear(self) -> None:
        self._document = None
        super().clear()

    def _reload(self) -> None:
        super().clear()
        if self._document is None:
            return
        self._add(self.invisibleRootItem(), self._document)
        self.expandToDepth(self._depth - 1)

    def _add(self, parent: QTreeWidgetItem, value: object, key: str | None = None) -> None:
        if isinstance(value, dict):
            items = value.items()
        elif isinstance(value, list):
            items = ((f"[{index}]", item) for index, item in enumerate(value))
        else:
            items = None
        if key is None and items is not None:
            for child_key, child in items:
                self._add(parent, child, str(child_key))
            return
        if items is not None:
            size = len(value)  # type: ignore[arg-type]
            summary = (
                "{" + i18n.tr_n("json.keys", size) + "}"
                if isinstance(value, dict)
                else "[" + i18n.tr_n("json.items", size) + "]"
            )
            node = QTreeWidgetItem(parent, [str(key), summary])
            for child_key, child in items:
                self._add(node, child, str(child_key))
        else:
            text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            QTreeWidgetItem(parent, [str(key), text])
