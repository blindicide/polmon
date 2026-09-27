"""Qt item models for large, append-only data (telemetry events)."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from polmon.client import theme
from polmon.client.formatting import compact_json, format_time
from polmon.client.i18n import has, tr

Index = QModelIndex | QPersistentModelIndex
CATEGORIES = (
    "scenario",
    "node_lifecycle",
    "network_observation",
    "execution_error",
    "resource",
)
# A glyph per category so the category column never depends on colour alone.
CATEGORY_GLYPHS = {
    "scenario": "▸",
    "node_lifecycle": "○",
    "network_observation": "✓",
    "execution_error": "✕",
    "resource": "▪",
}


def category_label(category: str) -> str:
    key = f"category.{category}"
    return tr(key) if has(key) else category.replace("_", " ")


CATEGORY_TONES = {
    "scenario": "info",
    "node_lifecycle": "muted",
    "network_observation": "success",
    "execution_error": "danger",
    "resource": "warning",
}


class TelemetryModel(QAbstractTableModel):
    """Append-only event rows, bounded to ``capacity`` (oldest rows are dropped)."""

    HEADERS = (
        "column.number",
        "column.time",
        "column.category",
        "column.event",
        "column.node",
        "column.payload",
    )

    def __init__(self, capacity: int = 20_000, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        from polmon.client.widgets import monospace_font

        self.mono = monospace_font()
        self.capacity = capacity
        self.events: list[dict[str, object]] = []
        self.last_sequence = 0
        self.dropped = 0

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.events)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802, ANN001
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.HEADERS[section])
        return None

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        event = self.events[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            category = str(event.get("category"))
            return (
                event.get("sequence"),
                format_time(event.get("timestamp")),
                f"{CATEGORY_GLYPHS.get(category, '·')} {category_label(category)}",
                event.get("event"),
                event.get("node_id") or "",
                compact_json(event.get("payload") or {}),
            )[column]
        if role == Qt.ItemDataRole.FontRole and column in {3, 4, 5}:
            return self.mono
        if role == Qt.ItemDataRole.ForegroundRole and column == 2:
            return theme.color(CATEGORY_TONES.get(str(event.get("category")), "muted"))
        if role == Qt.ItemDataRole.ToolTipRole and column == 5:
            return compact_json(event.get("payload") or {}, limit=2000)
        if role == Qt.ItemDataRole.UserRole:
            return event
        return None

    def retranslate(self) -> None:
        """Headers and category words follow a language switch."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.HEADERS) - 1)
        if self.events:
            self.dataChanged.emit(self.index(0, 2), self.index(len(self.events) - 1, 2))

    def clear(self) -> None:
        self.beginResetModel()
        self.events = []
        self.last_sequence = 0
        self.dropped = 0
        self.endResetModel()

    def append(self, events: list[dict[str, object]]) -> int:
        fresh = [
            item
            for item in events
            if int(item.get("sequence") or 0) > self.last_sequence  # type: ignore[arg-type]
        ]
        if not fresh:
            return 0
        overflow = len(self.events) + len(fresh) - self.capacity
        if overflow > 0:
            overflow = min(overflow, len(self.events))
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self.events[:overflow]
            self.endRemoveRows()
            self.dropped += overflow
        first = len(self.events)
        self.beginInsertRows(QModelIndex(), first, first + len(fresh) - 1)
        self.events.extend(fresh)
        self.endInsertRows()
        self.last_sequence = int(fresh[-1].get("sequence") or self.last_sequence)  # type: ignore[arg-type]
        return len(fresh)


def search_text(event: dict[str, object]) -> str:
    """Lower-cased event, node and payload text that the text filter matches against."""
    return " ".join(
        (
            str(event.get("event") or ""),
            str(event.get("node_id") or ""),
            compact_json(event.get("payload") or {}, limit=4000),
        )
    ).lower()


class TelemetryFilter(QSortFilterProxyModel):
    """Category set plus case-insensitive text over event, node and payload."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.categories = set(CATEGORIES)
        self.text = ""
        self._search: dict[object, str] = {}  # sequence -> search text, computed once

    def setSourceModel(self, model) -> None:  # noqa: N802, ANN001 - Qt override
        super().setSourceModel(model)
        model.modelReset.connect(self._search.clear)

    def set_categories(self, categories: set[str]) -> None:
        self.beginFilterChange()
        self.categories = categories
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self.text = text.strip().lower()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row: int, parent: Index) -> bool:  # noqa: N802
        model = self.sourceModel()
        assert isinstance(model, TelemetryModel)
        event = model.events[row]
        if str(event.get("category")) not in self.categories:
            return False
        if not self.text:
            return True
        key = event.get("sequence")
        text = self._search.get(key)
        if text is None:
            text = self._search[key] = search_text(event)
        return self.text in text
