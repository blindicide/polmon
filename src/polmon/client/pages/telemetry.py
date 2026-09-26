"""Telemetry: experiment-scoped live event stream with filtering and the capture summary."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from polmon.client.formatting import format_bytes, pretty_json
from polmon.client.models import CATEGORIES, TelemetryFilter, TelemetryModel
from polmon.client.pages import Context, Page
from polmon.client.tasks import CancelToken
from polmon.client.widgets import StatusBadge, fill_table, make_table, monospace_font, muted

PAGE_SIZE = 1000


class TelemetryPage(Page):
    key = "telemetry"
    title = "Telemetry"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.experiment_id: str | None = None
        self.status: str | None = None
        self._polling = False

        top = QHBoxLayout()
        top.addWidget(QLabel("Experiment"))
        self.selector = QComboBox()
        self.selector.setAccessibleName("Experiment")
        self.selector.setMinimumWidth(300)
        self.selector.activated.connect(self._chosen)
        top.addWidget(self.selector)
        self.badge = StatusBadge()
        top.addWidget(self.badge)
        self.follow = QCheckBox("Follow live")
        self.follow.setChecked(True)
        self.follow.setToolTip("Poll for new events every second while the experiment runs")
        top.addWidget(self.follow)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_list)
        top.addWidget(self.refresh_button)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setToolTip("Save the events currently shown (filters applied) as CSV")
        self.export_button.clicked.connect(self.export_csv)
        top.addWidget(self.export_button)
        top.addStretch(1)
        self.root.addLayout(top)

        filters = QHBoxLayout()
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in CATEGORIES:
            box = QCheckBox(category.replace("_", " "))
            box.setChecked(True)
            box.toggled.connect(self._filter_changed)
            self.category_boxes[category] = box
            filters.addWidget(box)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter events, nodes, payloads…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        filters.addWidget(self.search, 1)
        self.count = muted()
        filters.addWidget(self.count)
        self.root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.model = TelemetryModel(parent=self)
        self.proxy = TelemetryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        header = self.table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self._event_selected)
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.empty = muted(
            "No experiment selected. Run one on the Scenarios page, or pick an experiment above "
            "(Refresh loads the list from the backend)."
        )
        table_layout.addWidget(self.empty)
        table_layout.addWidget(self.table, 1)
        splitter.addWidget(table_box)

        lower = QSplitter()
        payload_box = QGroupBox("Selected event")
        payload_layout = QVBoxLayout(payload_box)
        self.payload = QPlainTextEdit()
        self.payload.setAccessibleName("Selected event payload")
        self.payload.setReadOnly(True)
        self.payload.setFont(monospace_font())
        payload_layout.addWidget(self.payload)
        lower.addWidget(payload_box)
        capture_box = QGroupBox("Capture summary")
        capture_layout = QVBoxLayout(capture_box)
        self.capture = make_table(("Measure", "Value"), stretch=1)
        capture_layout.addWidget(self.capture)
        lower.addWidget(capture_box)
        lower.setSizes([600, 360])
        splitter.addWidget(lower)
        splitter.setSizes([460, 200])
        self.root.addWidget(splitter, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.session.experiments_changed.connect(self._refresh_selector)
        self._update_count()

    # -- selection ----------------------------------------------------------------------------

    def refresh_list(self) -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            "List experiments",
            lambda token, report: client.experiments(),
            on_success=lambda items: self.session.set_experiments(items),  # type: ignore[arg-type]
            banner=self.banner,
            quiet=True,
        )

    def _refresh_selector(self) -> None:
        current = self.experiment_id
        self.selector.blockSignals(True)
        self.selector.clear()
        seen = set()
        active = self.session.active_experiment
        if active:
            self.selector.addItem(f"{active}  (running)", active)
            seen.add(active)
        for item in self.session.experiments:
            experiment_id = str(item.get("experiment_id"))
            if experiment_id in seen:
                continue
            seen.add(experiment_id)
            self.selector.addItem(
                f"{experiment_id}  ·  {item.get('scenario_id')}  ·  {item.get('status')}",
                experiment_id,
            )
        index = self.selector.findData(current) if current else -1
        self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)

    def _chosen(self, index: int) -> None:
        experiment_id = self.selector.itemData(index)
        if experiment_id:
            self.show_experiment(str(experiment_id))

    def show_experiment(self, experiment_id: str) -> None:
        if experiment_id != self.experiment_id:
            self.experiment_id = experiment_id
            self.status = None
            self.model.clear()
            self.payload.clear()
            self.capture.setRowCount(0)
            self.badge.set_status("")
        index = self.selector.findData(experiment_id)
        if index < 0:
            self.selector.addItem(experiment_id, experiment_id)
            index = self.selector.count() - 1
        self.selector.setCurrentIndex(index)
        self._poll(force=True)

    # -- polling ------------------------------------------------------------------------------

    def _tick(self) -> None:
        if (
            self.isVisible()
            and self.follow.isChecked()
            and self.status
            not in {
                "succeeded",
                "failed",
                "timed_out",
                "cancelled",
                "error",
                "interrupted",
            }
        ):
            self._poll()

    def _poll(self, *, force: bool = False) -> None:
        experiment_id = self.experiment_id
        if not experiment_id or self._polling or not self.session.connected:
            return
        if not force and not self.isVisible():
            return
        client = self.session.client()
        after = self.model.last_sequence

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            events: list[dict[str, object]] = []
            cursor = after
            for _ in range(20):  # drain what is available now, bounded per poll
                page = client.telemetry(experiment_id, after=cursor, limit=PAGE_SIZE)
                events.extend(page)
                if len(page) < PAGE_SIZE or token.cancelled:
                    break
                cursor = int(page[-1]["sequence"])  # type: ignore[arg-type]
            return {"events": events, "record": client.experiment(experiment_id)}

        self._polling = True
        self.context.run(
            f"Telemetry {experiment_id}",
            work,
            on_success=lambda result: self._received(experiment_id, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._poll_failed(),
            banner=self.banner if force else None,
            quiet=True,
        )

    def _poll_failed(self) -> None:
        self._polling = False

    def _received(self, experiment_id: str, result: dict[str, object]) -> None:
        self._polling = False
        if experiment_id != self.experiment_id:
            return
        events = result.get("events") or []
        assert isinstance(events, list)
        at_bottom = self.table.verticalScrollBar().value() >= (
            self.table.verticalScrollBar().maximum() - 2
        )
        added = self.model.append(events)
        if added and at_bottom:
            self.table.scrollToBottom()
        record = result.get("record") or {}
        assert isinstance(record, dict)
        self.status = str(record.get("status"))
        self.badge.set_status(self.status)
        self._show_capture(record)
        self._update_count()

    def _show_capture(self, record: dict[str, object]) -> None:
        capture = record.get("capture")
        progress = record.get("progress") or {}
        rows: list[tuple[str, object]] = []
        if isinstance(capture, dict):
            rows += [
                ("Frames captured", capture.get("frame_count")),
                ("Bytes captured", format_bytes(capture.get("captured_bytes"))),
                ("Frames dropped (capture limit)", capture.get("dropped_frames")),
                ("Frames truncated (snap length)", capture.get("truncated_frames")),
                ("Capture file (on the backend)", capture.get("path")),
            ]
        elif self.status in {"running", "cancelling"}:
            rows.append(("Capture", "written when the experiment finishes"))
        if isinstance(progress, dict) and progress:
            rows.append(
                (
                    "Actions completed",
                    f"{progress.get('completed_actions')}/{progress.get('total_actions')}",
                )
            )
        rows.append(("Events received", len(self.model.events) + self.model.dropped))
        fill_table(self.capture, rows)

    def _filter_changed(self) -> None:
        self.proxy.set_categories(
            {name for name, box in self.category_boxes.items() if box.isChecked()}
        )
        self.proxy.set_text(self.search.text())
        self._update_count()

    def _update_count(self) -> None:
        self.export_button.setEnabled(self.model.rowCount() > 0)
        self.empty.setVisible(self.experiment_id is None)
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        dropped = f" ({self.model.dropped} oldest dropped)" if self.model.dropped else ""
        self.count.setText(f"{shown} of {total} events{dropped}")

    def visible_events(self) -> list[dict[str, object]]:
        return [
            self.proxy.data(self.proxy.index(row, 0), Qt.ItemDataRole.UserRole)
            for row in range(self.proxy.rowCount())
        ]

    def write_csv(self, path: Path) -> int:
        """Write the filtered events to ``path``; returns the number of rows."""
        events = self.visible_events()
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sequence", "timestamp", "category", "event", "node_id", "payload"])
            for event in events:
                writer.writerow(
                    [
                        event.get("sequence"),
                        event.get("timestamp"),
                        event.get("category"),
                        event.get("event"),
                        event.get("node_id") or "",
                        json.dumps(event.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                    ]
                )
        return len(events)

    def export_csv(self) -> None:
        if not self.experiment_id:
            return
        path = self.context.ask_save(
            self, "Export telemetry", f"{self.experiment_id}-telemetry.csv", "CSV (*.csv)"
        )
        if path is None:
            return
        try:
            count = self.write_csv(path)
        except OSError as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.session.log(f"Exported {count} telemetry events to {path}")

    def _event_selected(self, current, previous) -> None:  # noqa: ANN001
        event = self.proxy.data(current, Qt.ItemDataRole.UserRole) if current.isValid() else None
        self.payload.setPlainText(pretty_json(event) if event else "")

    def refresh_actions(self) -> None:
        self.refresh_button.setEnabled(self.session.connected)
        self.export_button.setEnabled(bool(self.experiment_id))

    def activated(self, argument: object = None) -> None:
        if self.session.connected and not self.session.experiments:
            self.refresh_list()
        if isinstance(argument, str):
            self.show_experiment(argument)
        elif self.session.active_experiment and not self.experiment_id:
            self.show_experiment(self.session.active_experiment)
