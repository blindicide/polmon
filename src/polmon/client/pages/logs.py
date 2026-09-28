"""Detailed structured lab logs, separate from the experiment event telemetry view."""

from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from polmon.client.i18n import Msg, bind, bind_text, tr
from polmon.client.pages import Context, Page
from polmon.client.widgets import Card, StateView, accessible, button, label, monospace_font


class LogsPage(Page):
    key = "logs"

    HEADERS = (
        "logs.column.cursor",
        "logs.column.time",
        "logs.column.level",
        "logs.column.event",
        "logs.column.node",
        "logs.column.message",
    )

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.records: list[dict[str, object]] = []
        self.cursor = 0
        self._request_active = False

        source = Card("logs.filters", name="filters")
        row = QHBoxLayout()
        row.addWidget(label("logs.level", name="fieldLabel"))
        self.level = QComboBox()
        self.level.setObjectName("logLevel")
        accessible(self.level, "a11y.log_level")
        for value in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.level.addItem(value, value)
        row.addWidget(self.level)
        self.source_filter = QLineEdit()
        self.source_filter.setObjectName("logSource")
        bind(self.source_filter, "setPlaceholderText", "logs.source_placeholder")
        row.addWidget(self.source_filter, 1)
        self.deployment_filter = QLineEdit()
        self.deployment_filter.setObjectName("logDeployment")
        bind(self.deployment_filter, "setPlaceholderText", "logs.deployment_placeholder")
        row.addWidget(self.deployment_filter, 1)
        self.node_filter = QLineEdit()
        self.node_filter.setObjectName("logNode")
        bind(self.node_filter, "setPlaceholderText", "logs.node_placeholder")
        row.addWidget(self.node_filter, 1)
        self.search = QLineEdit()
        self.search.setObjectName("logSearch")
        bind(self.search, "setPlaceholderText", "logs.search_placeholder")
        row.addWidget(self.search, 2)
        self.follow = QCheckBox()
        self.follow.setObjectName("logFollow")
        bind_text(self.follow, "logs.follow")
        self.follow.setChecked(True)
        row.addWidget(self.follow)
        self.refresh_button = button("common.refresh", "quiet", name="refreshLogs")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        self.files_button = button("logs.files", "quiet", name="logFiles")
        self.files_button.clicked.connect(self.show_files)
        row.addWidget(self.files_button)
        self.export_button = button("logs.export", "quiet", name="exportLogs")
        self.export_button.clicked.connect(self.export)
        row.addWidget(self.export_button)
        self.copy_button = button("logs.copy", "quiet", name="copyLog")
        self.copy_button.clicked.connect(self.copy_selected)
        row.addWidget(self.copy_button)
        source.body.addLayout(row)
        self.root.addWidget(source)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        events = Card("logs.records", name="records")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("logsTable")
        self.table.setHorizontalHeaderLabels([tr(key) for key in self.HEADERS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 230)
        self.state = StateView(self.table)
        events.add(self.state, 1)
        splitter.addWidget(events)
        detail = Card("logs.detail", name="detail")
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("logDetail")
        self.detail.setReadOnly(True)
        self.detail.setFont(monospace_font())
        bind(self.detail, "setPlaceholderText", "logs.detail_placeholder")
        detail.add(self.detail, 1)
        splitter.addWidget(detail)
        splitter.setSizes([700, 500])
        self.root.addWidget(splitter, 1)

        for widget in (
            self.level,
            self.source_filter,
            self.deployment_filter,
            self.node_filter,
            self.search,
        ):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._filters_changed)
            else:
                widget.textChanged.connect(self._filters_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.refresh_actions()

    def retranslate(self) -> None:
        for index, key in enumerate(self.HEADERS):
            self.table.horizontalHeaderItem(index).setText(tr(key))
        self.level.setItemText(0, tr("logs.level.debug"))
        self.level.setItemText(1, tr("logs.level.info"))
        self.level.setItemText(2, tr("logs.level.warning"))
        self.level.setItemText(3, tr("logs.level.error"))

    def _filters_changed(self) -> None:
        self.cursor = 0
        self.records = []
        self.refresh()

    def _tick(self) -> None:
        if self.isVisible() and self.follow.isChecked():
            self.refresh()

    def refresh(self) -> None:
        if not self.session.connected or self._request_active:
            return
        self._request_active = True
        client = self.session.client()
        self.context.run(
            Msg("operation.logs"),
            lambda token, report: client.logs(
                level=str(self.level.currentData()),
                source=self.source_filter.text().strip() or None,
                deployment=self.deployment_filter.text().strip() or None,
                node=self.node_filter.text().strip() or None,
                search=self.search.text().strip() or None,
                since=self.cursor if self.follow.isChecked() else 0,
                limit=200,
            ),
            on_success=self._received,
            on_failure=self._failed,
            banner=self.banner,
            quiet=True,
        )

    def _received(self, result: object) -> None:
        self._request_active = False
        if not isinstance(result, dict):
            return
        records = result.get("records")
        if not isinstance(records, list):
            return
        if not self.follow.isChecked() or self.cursor == 0:
            self.records = [item for item in records if isinstance(item, dict)]
        else:
            self.records.extend(item for item in records if isinstance(item, dict))
            self.records = self.records[-5000:]
        self.cursor = int(result.get("next_cursor") or self.cursor)
        self._render()

    def _failed(self, error: BaseException) -> None:
        self._request_active = False
        self.banner.show_problem(self.context.problem(error))

    def _render(self) -> None:
        self.table.setRowCount(0)
        for record in self.records:
            correlation = record.get("correlation")
            node = correlation.get("node") if isinstance(correlation, dict) else {}
            node_id = node.get("id", "") if isinstance(node, dict) else ""
            values = (
                record.get("cursor", ""),
                record.get("timestamp", ""),
                record.get("level", ""),
                record.get("event", ""),
                node_id,
                tr("logs.record_available"),
            )
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.state.show_content() if self.records else self.state.show_empty(
            Msg("logs.empty"), Msg("logs.empty_hint")
        )
        self.copy_button.setEnabled(bool(self.records))
        self.export_button.setEnabled(bool(self.records))

    def _selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail.clear()
            return
        index = rows[0].row()
        if 0 <= index < len(self.records):
            self.detail.setPlainText(json.dumps(self.records[index], indent=2, ensure_ascii=False))

    def copy_selected(self) -> None:
        if self.detail.toPlainText():
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(self.detail.toPlainText())

    def export(self) -> None:
        path = self.context.ask_save(self, "logs.export_dialog", "polmon-logs.json", "json")
        if path is None:
            return
        try:
            path.write_text(
                json.dumps(self.records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.session.log(Msg("logs.exported", count=len(self.records), path=path))

    def show_files(self) -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.log_files"),
            lambda token, report: client.log_files(),
            on_success=lambda result: self.detail.setPlainText(
                json.dumps(result, indent=2, ensure_ascii=False)
            ),
            banner=self.banner,
            quiet=True,
        )

    def refresh_actions(self) -> None:
        connected = self.session.connected
        self.refresh_button.setEnabled(connected)
        self.files_button.setEnabled(connected)

    def activated(self, argument: object = None) -> None:
        del argument
        self.refresh()
