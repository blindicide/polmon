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
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTableView,
    QWidget,
)

from polmon.client import theme
from polmon.client.formatting import format_bytes, pretty_json, size
from polmon.client.i18n import Msg, bind, bind_text, bind_tip, status_label, tr, tr_n
from polmon.client.models import CATEGORIES, TelemetryFilter, TelemetryModel
from polmon.client.pages import Context, Page
from polmon.client.tasks import CancelToken
from polmon.client.widgets import (
    RAW_ROLE,
    Card,
    StateView,
    StatusBadge,
    accessible,
    button,
    fill_table,
    label,
    make_table,
    monospace_font,
)

PAGE_SIZE = 1000
FINISHED = {"succeeded", "failed", "timed_out", "cancelled", "error", "interrupted"}


class TelemetryPage(Page):
    key = "telemetry"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.experiment_id: str | None = None
        self.status: str | None = None
        self.record: dict[str, object] = {}
        self._polling = False

        source = Card("telemetry.source", name="source")
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE["sm"])
        top.addWidget(label("telemetry.experiment", name="fieldLabel"))
        self.selector = QComboBox()
        self.selector.setObjectName("experimentSelector")
        accessible(self.selector, "a11y.experiment_selector")
        self.selector.setFont(monospace_font())
        self.selector.setMinimumWidth(300)
        self.selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.selector.setMinimumContentsLength(40)
        self.selector.activated.connect(self._chosen)
        top.addWidget(self.selector)
        self.badge = StatusBadge()
        top.addWidget(self.badge)
        self.follow = QCheckBox()
        self.follow.setObjectName("followLive")
        bind_text(self.follow, "telemetry.follow")
        bind_tip(self.follow, "telemetry.follow.tip")
        self.follow.setChecked(True)
        top.addStretch(1)
        self.refresh_button = button("common.refresh", "quiet", tip="telemetry.refresh.tip",
                                     name="refreshButton")
        self.refresh_button.clicked.connect(self.refresh_list)
        top.addWidget(self.refresh_button)
        self.export_button = button("telemetry.export", "primary", tip="telemetry.export.tip",
                                    name="exportCsv")
        self.export_button.clicked.connect(self.export_csv)
        top.addWidget(self.export_button)
        self.capture_button = button("telemetry.save_capture", tip="telemetry.save_capture.tip",
                                     name="saveCapture")
        self.capture_button.clicked.connect(self.save_capture)
        self.capture_button.setEnabled(False)
        top.addWidget(self.capture_button)
        source.body.addLayout(top)

        filters = QHBoxLayout()
        filters.setSpacing(theme.SPACE["md"])
        filters.addWidget(label("telemetry.categories", name="sectionLabel"))
        self.category_boxes: dict[str, QCheckBox] = {}
        for category in CATEGORIES:
            box = QCheckBox()
            box.setObjectName(f"category_{category}")
            bind(box, "setText", f"category.{category}")
            box.setChecked(True)
            box.toggled.connect(self._filter_changed)
            self.category_boxes[category] = box
            filters.addWidget(box)
        self.search = QLineEdit()
        self.search.setObjectName("telemetrySearch")
        bind(self.search, "setPlaceholderText", "telemetry.search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        search_row = QHBoxLayout()
        search_row.setSpacing(theme.SPACE["md"])
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.follow)
        self.count = label(name="muted")
        self.count.setObjectName("eventCount")
        search_row.addWidget(self.count)
        filters.addStretch(1)
        source.body.addLayout(filters)
        source.body.addLayout(search_row)
        self.root.addWidget(source)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.model = TelemetryModel(parent=self)
        self.proxy = TelemetryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setObjectName("telemetryTable")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((56, 110, 200, 190, 130)):
            header.resizeSection(column, width)
        self.table.selectionModel().currentRowChanged.connect(self._event_selected)
        events = Card("telemetry.events", name="events")
        self.table_state = StateView(self.table)
        events.add(self.table_state, 1)
        splitter.addWidget(events)

        lower = QSplitter()
        lower.setChildrenCollapsible(False)
        payload_card = Card("telemetry.selected", name="payload")
        self.payload = QPlainTextEdit()
        self.payload.setObjectName("eventPayload")
        self.payload.setReadOnly(True)
        self.payload.setFont(monospace_font())
        bind(self.payload, "setPlaceholderText", "telemetry.selected.placeholder")
        payload_card.add(self.payload, 1)
        lower.addWidget(payload_card)
        capture_card = Card("telemetry.capture", name="capture")
        self.capture = make_table(("column.measure", "column.value"), stretch=1, sortable=False,
                                  name="captureSummary")
        capture_card.add(self.capture, 1)
        lower.addWidget(capture_card)
        lower.setSizes([700, 480])
        splitter.addWidget(lower)
        splitter.setSizes([470, 210])
        self.root.addWidget(splitter, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.session.experiments_changed.connect(self._refresh_selector)
        self._update_count()

    def retranslate(self) -> None:
        self.model.retranslate()
        self._refresh_selector()
        self._show_capture(self.record)
        self._update_count()

    # -- selection ----------------------------------------------------------------------------

    def refresh_list(self) -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.list_experiments"),
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
            self.selector.addItem(tr("telemetry.running_item", experiment=active), active)
            seen.add(active)
        for item in self.session.experiments:
            experiment_id = str(item.get("experiment_id"))
            if experiment_id in seen:
                continue
            seen.add(experiment_id)
            self.selector.addItem(
                f"{experiment_id}  ·  {item.get('scenario_id')}  ·  "
                f"{status_label(item.get('status'))}",
                experiment_id,
            )
        index = self.selector.findData(current) if current else -1
        if current and index < 0:
            self.selector.addItem(current, current)
            index = self.selector.count() - 1
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
            self.record = {}
            self.model.clear()
            self.payload.clear()
            self.capture.setRowCount(0)
            self.badge.set_status("")
            self.capture_button.setEnabled(False)
        index = self.selector.findData(experiment_id)
        if index < 0:
            self.selector.addItem(experiment_id, experiment_id)
            index = self.selector.count() - 1
        self.selector.setCurrentIndex(index)
        self._update_count()
        self._poll(force=True)

    # -- polling ------------------------------------------------------------------------------

    def _tick(self) -> None:
        if self.isVisible() and self.follow.isChecked() and self.status not in FINISHED:
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
            Msg("operation.telemetry", experiment=experiment_id),
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
        self.record = record
        self.status = str(record.get("status"))
        self.badge.set_status(self.status)
        self.capture_button.setEnabled(isinstance(record.get("capture"), dict))
        self._show_capture(record)
        self._update_count()

    def _show_capture(self, record: dict[str, object]) -> None:
        capture = record.get("capture")
        progress = record.get("progress") or {}
        rows: list[tuple[str, object]] = []
        if isinstance(capture, dict):
            rows += [
                ("capture.frames", capture.get("frame_count")),
                ("capture.bytes", format_bytes(capture.get("captured_bytes"))),
                ("capture.dropped", capture.get("dropped_frames")),
                ("capture.truncated", capture.get("truncated_frames")),
                ("capture.file", capture.get("path")),
            ]
        elif self.status in {"running", "cancelling"}:
            rows.append(("capture.title", tr("capture.pending")))
        if isinstance(progress, dict) and progress:
            rows.append(
                (
                    "capture.actions",
                    f"{progress.get('completed_actions')}/{progress.get('total_actions')}",
                )
            )
        if self.experiment_id:
            rows.append(("capture.events", len(self.model.events) + self.model.dropped))
        fill_table(self.capture, [(tr(key), value) for key, value in rows])
        for row, (key, _) in enumerate(rows):
            item = self.capture.item(row, 0)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole, key)
                value_item = self.capture.item(row, 1)
                if value_item is not None:
                    value_item.setData(RAW_ROLE, rows[row][1])

    def _filter_changed(self) -> None:
        self.proxy.set_categories(
            {name for name, box in self.category_boxes.items() if box.isChecked()}
        )
        self.proxy.set_text(self.search.text())
        self._update_count()

    def _update_count(self) -> None:
        self.export_button.setEnabled(self.model.rowCount() > 0)
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        text = tr("telemetry.count", shown=shown, total=tr_n("count.events", total))
        if self.model.dropped:
            text += " " + tr("telemetry.dropped", count=self.model.dropped)
        self.count.setText(text)
        if self.experiment_id is None:
            self.table_state.show_empty(Msg("telemetry.none"), Msg("telemetry.none_hint"))
        elif total == 0 and self.status is None:
            self.table_state.show_loading(Msg("telemetry.loading"))
        elif total == 0:
            self.table_state.show_empty(Msg("telemetry.no_events"))
        else:
            self.table_state.show_content()

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
            self, "telemetry.export.dialog", f"{self.experiment_id}-telemetry.csv", "csv"
        )
        if path is None:
            return
        try:
            count = self.write_csv(path)
        except OSError as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.session.log(Msg("log.exported", count=count, path=path))

    def save_capture(self, path: Path | None = None) -> None:
        """Download the capture of the shown experiment into ``path`` (asks when omitted)."""
        experiment_id = self.experiment_id
        if not experiment_id:
            return
        if path is None:
            path = self.context.ask_save(
                self, "telemetry.save_capture.dialog", f"{experiment_id}.pcap", "pcap"
            )
            if path is None:
                return
        client = self.session.client(timeout=max(30.0, self.session.timeout))
        target = path

        def work(token: CancelToken, report) -> int:  # noqa: ANN001
            data = client.capture(experiment_id)
            target.write_bytes(data)
            return len(data)

        self.context.run(
            Msg("operation.save_capture", experiment=experiment_id),
            work,
            on_success=lambda written: self.session.log(
                Msg("log.capture_saved", size=size(written), path=target)
            ),
            banner=self.banner,
        )

    def _event_selected(self, current, previous) -> None:  # noqa: ANN001
        event = self.proxy.data(current, Qt.ItemDataRole.UserRole) if current.isValid() else None
        self.payload.setPlainText(pretty_json(event) if event else "")

    def refresh_actions(self) -> None:
        self.refresh_button.setEnabled(self.session.connected)
        self.export_button.setEnabled(bool(self.experiment_id) and self.model.rowCount() > 0)

    def activated(self, argument: object = None) -> None:
        if self.session.connected and not self.session.experiments:
            self.refresh_list()
        if isinstance(argument, str):
            self.show_experiment(argument)
        elif self.session.active_experiment and not self.experiment_id:
            self.show_experiment(self.session.active_experiment)

