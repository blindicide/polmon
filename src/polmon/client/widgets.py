"""Reusable, theme-aware widgets for a dense operator console."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Sequence

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPainterPath,
    QPen,
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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from polmon.client import theme
from polmon.client.errors import Problem
from polmon.client.formatting import progress_text
from polmon.client.tasks import ProgressUpdate, TaskHandle


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
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def page_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("pageTitle")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primary")
    return button


def make_table(headers: Sequence[str], *, stretch: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(22)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(stretch is None)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return table


def fill_table(
    table: QTableWidget,
    rows: Iterable[Sequence[object]],
    *,
    colors: dict[int, str] | None = None,
    data: Sequence[object] | None = None,
) -> None:
    """Replace all rows; ``colors`` maps a column to a status whose colour tints its text."""
    rows = list(rows)
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            item = QTableWidgetItem("—" if value is None else str(value))
            if colors and column in colors:
                item.setForeground(theme.color(theme.status_color(str(value))))
            if data is not None and column == 0:
                item.setData(Qt.ItemDataRole.UserRole, data[row_index])
            table.setItem(row_index, column, item)


class StatusBadge(ThemeAware, QLabel):
    """A coloured pill such as SUCCEEDED / FAILED / RUNNING."""

    def __init__(self, status: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        self._status = status
        self.setText(status.replace("_", " ").upper() if status else "")
        self.setVisible(bool(status))
        self.restyle()

    @property
    def status(self) -> str:
        return self._status

    def restyle(self) -> None:
        tone = theme.hex_color(theme.status_color(self._status or ""))
        self.setStyleSheet(
            f"QLabel {{ color: {tone}; border: 1px solid {tone}; border-radius: 9px;"
            " padding: 1px 9px; font-weight: 600; }"
        )


class Led(ThemeAware, QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._tone = "muted"
        self.restyle()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.restyle()

    def restyle(self) -> None:
        self.setStyleSheet(
            f"QLabel {{ background: {theme.hex_color(self._tone)}; border-radius: 6px; }}"
        )


class ProblemBanner(ThemeAware, QFrame):
    """Inline, dismissible explanation of the last failure (never a modal stall)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._severity = "danger"
        self.problem: Problem | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 6, 6)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setToolTip("Dismiss")
        close.clicked.connect(self.clear)
        layout.addWidget(self.label, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()

    def show_problem(self, problem: Problem, severity: str = "danger") -> None:
        self.problem = problem
        self._severity = severity
        items = "".join(f"<li>{_escape(item)}</li>" for item in problem.items)
        hint = f"<div>{_escape(problem.hint)}</div>" if problem.hint else ""
        self.label.setText(
            f"<b>{_escape(problem.title)}</b> — {_escape(problem.detail)}"
            + (f"<ul style='margin:2px 0 2px -20px'>{items}</ul>" if items else "")
            + hint
        )
        self.restyle()
        self.show()

    def show_message(self, title: str, detail: str, severity: str = "info") -> None:
        self.show_problem(Problem(title, detail), severity)

    def clear(self) -> None:
        self.problem = None
        self.hide()

    def restyle(self) -> None:
        tone = theme.hex_color(self._severity)
        background = theme.hex_color(f"banner_{self._severity}")
        self.setStyleSheet(
            f"ProblemBanner {{ background: {background}; border: 1px solid {tone};"
            " border-radius: 6px; }"
        )


def _escape(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Sparkline(QWidget):
    """Minimal line chart of the last ``capacity`` samples (QPainter; no chart library)."""

    def __init__(self, capacity: int = 120, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.samples: deque[float] = deque(maxlen=capacity)
        self.setMinimumHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(120, 28)

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
        step = area.width() / (self.samples.maxlen - 1 if self.samples.maxlen else 1)
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
        painter.fillPath(fill, QColor(theme.hex_color("chart_fill")))
        painter.setPen(QPen(theme.color("chart"), 1.5))
        painter.drawPath(path)


class CounterTile(QFrame):
    """Caption, big value, secondary line and an optional sparkline."""

    def __init__(self, caption: str, *, sparkline: bool = False, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("tile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(1)
        self.caption = QLabel(caption)
        self.caption.setObjectName("tileCaption")
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        self.secondary = QLabel("")
        self.secondary.setObjectName("tileCaption")
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.secondary)
        self.sparkline = Sparkline() if sparkline else None
        if self.sparkline is not None:
            layout.addWidget(self.sparkline)
        self.setMinimumWidth(130)

    def set(self, value: str, secondary: str = "", sample: float | None = None) -> None:
        self.value.setText(value)
        self.secondary.setText(secondary)
        if self.sparkline is not None:
            self.sparkline.add(sample)


class OperationProgress(QWidget):
    """Status-bar progress for the current long operation: percent, step, elapsed, ETA, Cancel."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.bar = QProgressBar()
        self.bar.setFixedWidth(160)
        self.bar.setTextVisible(True)
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.cancel = QPushButton("Cancel")
        self.cancel.setToolTip("Cancel the running operation (Esc)")
        self.cancel.clicked.connect(self.cancel_requested)
        for widget in (self.title, self.bar, self.detail, self.cancel):
            layout.addWidget(widget)
        self.handle: TaskHandle | None = None
        self.update_: ProgressUpdate | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._render)
        self.hide()

    def track(self, handle: TaskHandle, title: str, *, cancellable: bool = True) -> None:
        self.handle = handle
        self.update_ = None
        self.title.setText(title)
        self.cancel.setVisible(cancellable)
        self.bar.setRange(0, 0)  # busy until the first progress report
        handle.progress.connect(self._progress)
        handle.finished.connect(lambda: self._finished(handle))
        self.timer.start()
        self._render()
        self.show()

    def _progress(self, update: ProgressUpdate) -> None:
        self.update_ = update
        self._render()

    def _render(self) -> None:
        if self.handle is None:
            return
        update = self.update_
        elapsed = self.handle.elapsed
        if update is None or not update.total:
            self.bar.setRange(0, 0)
            self.detail.setText(f"{elapsed:.1f} s elapsed")
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
            self.hide()


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
        self.setPlaceholderText("Open a YAML file (Ctrl+O) or paste a document here.")
        self._gutter = _LineNumbers(self)
        self._error_line: int | None = None
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._scroll_gutter)
        self._update_margins()

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

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
        painter.fillRect(event.rect(), theme.color("alternate"))
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
                    self._gutter.width() - 5,
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
        self.setHeaderLabels(["Key", "Value"])
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(True)

    def load(self, document: object, *, expand_depth: int = 1) -> None:
        self.clear()
        self._add(self.invisibleRootItem(), document)
        self.expandToDepth(expand_depth - 1)

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
            summary = f"{{{size} keys}}" if isinstance(value, dict) else f"[{size} items]"
            node = QTreeWidgetItem(parent, [str(key), summary])
            for child_key, child in items:
                self._add(node, child, str(child_key))
        else:
            text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            QTreeWidgetItem(parent, [str(key), text])
