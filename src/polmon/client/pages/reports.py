"""Reports: experiment list, overall status, expected vs actual, Markdown and JSON views."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QSplitter, QTabWidget, QTextBrowser, QWidget

from polmon.client.api import ApiClientError
from polmon.client.formatting import (
    duration_between,
    format_bytes,
    format_datetime,
    format_seconds,
)
from polmon.client.i18n import Msg, bind, tr
from polmon.client.pages import Context, Page
from polmon.client.pages.scenarios import experiment_errors
from polmon.client.reportview import experiment_markdown
from polmon.client.tasks import CancelToken
from polmon.client.widgets import (
    Card,
    JsonTree,
    StateView,
    StatusBadge,
    button,
    cell_text,
    fill_table,
    label,
    make_table,
)


class ReportsPage(Page):
    key = "reports"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.report: dict[str, object] | None = None
        self.markdown = ""
        self.markdown_missing = False
        self.experiment_id: str | None = None

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        list_card = Card("reports.list", hint="reports.list.hint", name="list")
        self.refresh_button = button("common.refresh", "quiet", tip="reports.refresh.tip",
                                     name="refreshButton")
        self.refresh_button.clicked.connect(self.refresh_list)
        list_card.add_action(self.refresh_button)
        self.filter = QLineEdit()
        self.filter.setObjectName("reportFilter")
        bind(self.filter, "setPlaceholderText", "reports.filter")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        list_card.add(self.filter)
        self.list = make_table(
            (
                "column.experiment",
                "column.scenario",
                "column.topology",
                "column.status",
                "column.started",
            ),
            stretch=None,
            mono=(0, 2),
            name="experimentList",
        )
        self.list.itemSelectionChanged.connect(self._chosen)
        self.list_state = StateView(self.list)
        list_card.add(self.list_state, 1)
        splitter.addWidget(list_card)

        report_card = Card(name="report")
        header = QHBoxLayout()
        self.title_label = label(name="cardTitle")
        self.title_label.setObjectName("reportTitle")
        self.status = StatusBadge()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.status)
        self.save_json = button("reports.save_json", "quiet", name="saveJson")
        self.save_markdown = button("reports.save_markdown", "quiet", name="saveMarkdown")
        self.save_json.clicked.connect(lambda: self._save("json"))
        self.save_markdown.clicked.connect(lambda: self._save("md"))
        header.addWidget(self.save_json)
        header.addWidget(self.save_markdown)
        report_card.body.addLayout(header)
        self.meta = label(name="muted", wrap=True)
        self.meta.setObjectName("reportMeta")
        report_card.add(self.meta)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("reportTabs")
        self.comparison = make_table(
            (
                "column.role",
                "column.action",
                "column.field",
                "column.expected",
                "column.actual",
                "column.outcome",
            ),
            stretch=None,
            mono=(1,),
            name="comparison",
        )
        self.observations = make_table(
            ("column.event", "column.success", "column.detail", "column.data"), stretch=3,
            mono=(0, 3), name="observations",
        )
        self.errors = make_table(("column.error",), stretch=0, name="reportErrors")
        self.resources = make_table(("column.statistic", "column.value"), stretch=1,
                                    sortable=False, name="reportResources")
        self.rendered = QTextBrowser()
        self.rendered.setObjectName("reportMarkdown")
        self.rendered.setOpenExternalLinks(False)
        self.json = JsonTree()
        self.json.setObjectName("reportJson")
        for widget in (
            self.comparison, self.observations, self.errors, self.resources, self.rendered,
            self.json,
        ):
            self.tabs.addTab(widget, "")
        self.report_state = StateView(self.tabs)
        report_card.add(self.report_state, 1)
        splitter.addWidget(report_card)
        splitter.setSizes([470, 790])
        self.root.addWidget(splitter, 1)

        self.session.experiments_changed.connect(self._fill_list)
        self.retranslate()
        self.refresh_actions()

    def retranslate(self) -> None:
        errors = len(self.report.get("errors") or []) if self.report else 0  # type: ignore[union-attr]
        titles = (
            tr("reports.tab.comparison"),
            tr("reports.tab.observations"),
            tr("reports.tab.errors_count", count=errors) if errors else tr("reports.tab.errors"),
            tr("reports.tab.resources"),
            tr("reports.tab.markdown"),
            tr("reports.tab.json"),
        )
        for index, title in enumerate(titles):
            self.tabs.setTabText(index, title)
        self._fill_list()
        if self.report is not None and self.experiment_id is not None:
            self._render(self.experiment_id)
        elif self.experiment_id is None:
            self.title_label.setText(tr("reports.select"))
            self.meta.setText("")
            self.report_state.show_empty(Msg("reports.none_selected"),
                                         Msg("reports.none_selected_hint"))

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

    def _fill_list(self) -> None:
        experiments = self.session.experiments
        selected = self.experiment_id
        rows = [
            (
                item.get("experiment_id"),
                item.get("scenario_id"),
                item.get("topology_id"),
                item.get("status"),
                format_datetime(item.get("started_at")),
            )
            for item in experiments
        ]
        if rows:
            self.list_state.show_content()
        elif self.session.connected:
            self.list_state.show_empty(Msg("reports.empty"), Msg("reports.empty_hint"))
        else:
            self.list_state.show_empty(Msg("common.offline"), Msg("common.offline_hint"))
        self.list.blockSignals(True)
        fill_table(self.list, rows, colors={3: "status"}, data=[row[0] for row in rows])
        for index in range(self.list.rowCount()):
            item = self.list.item(index, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected:
                self.list.selectRow(index)
        self.list.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.filter.text().strip().lower()
        for row in range(self.list.rowCount()):
            text = " ".join(
                (self.list.item(row, column).text() if self.list.item(row, column) else "")
                for column in range(4)
            ).lower()
            self.list.setRowHidden(row, bool(needle) and needle not in text)

    def _chosen(self) -> None:
        rows = self.list.selectionModel().selectedRows()
        if rows:
            item = self.list.item(rows[0].row(), 0)
            identifier = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if identifier and identifier != self.experiment_id:
                self.open_report(str(identifier))

    def open_report(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        client = self.session.client()

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            document = client.report(experiment_id)
            try:
                markdown = client.report_markdown(experiment_id)
            except ApiClientError as error:
                if error.status not in {404, 405}:
                    raise
                markdown = None
            return {"report": document, "markdown": markdown}

        self.title_label.setText(experiment_id)
        self.meta.setText("")
        self.report_state.show_loading(Msg("reports.loading", experiment=experiment_id))
        self.context.run(
            Msg("operation.open_report", experiment=experiment_id),
            work,
            on_success=lambda result: self._show(experiment_id, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._failed(experiment_id),
            banner=self.banner,
            quiet=True,
        )

    def _failed(self, experiment_id: str) -> None:
        if experiment_id == self.experiment_id:
            self.report = None
            self.markdown = ""
            self.status.set_status("")
            self.report_state.show_error(Msg("reports.unavailable"),
                                         Msg("reports.unavailable_hint"))
            for table in (self.comparison, self.observations, self.errors, self.resources):
                table.setRowCount(0)
            self.rendered.clear()
            self.json.clear()
            self.refresh_actions()

    def _show(self, experiment_id: str, result: dict[str, object]) -> None:
        if experiment_id != self.experiment_id:
            return
        report = result["report"]
        assert isinstance(report, dict)
        self.report = report
        markdown = result.get("markdown")
        self.markdown_missing = markdown is None
        self.markdown = str(markdown or "")
        self.json.load(report)
        self.retranslate()
        self.refresh_actions()

    def _render(self, experiment_id: str) -> None:
        report = self.report
        assert report is not None
        execution = report.get("execution") or {}
        scenario = report.get("scenario") or {}
        topology = report.get("topology") or {}
        assert isinstance(execution, dict) and isinstance(scenario, dict)
        assert isinstance(topology, dict)
        status = str(report.get("status"))
        self.status.set_status(status)
        self.title_label.setText(experiment_id)
        duration = duration_between(execution.get("started_at"), execution.get("finished_at"))
        self.meta.setText(
            tr(
                "reports.meta",
                scenario=scenario.get("id"),
                topology=topology.get("id"),
                started=format_datetime(execution.get("started_at")),
                duration=format_seconds(duration),
                cleanup=tr("reports.cleanup.done")
                if execution.get("cleanup_performed")
                else tr("reports.cleanup.not_done"),
                version=report.get("polmon_version"),
            )
        )
        comparisons = report.get("expected_vs_actual") or []
        fill_table(
            self.comparison,
            [
                (
                    tr(f"condition.role.{item['role']}"),
                    item["action"],
                    item["field"],
                    cell_text(item["expected"]),
                    cell_text(item["actual"]),
                    item["outcome"].replace(" ", "_"),
                )
                for item in comparisons  # type: ignore[union-attr]
            ],
            colors={5: "outcome"},
        )
        observed = [
            event
            for event in report.get("observed_events") or []  # type: ignore[union-attr]
            if event.get("category") == "network_observation"
        ]
        fill_table(
            self.observations,
            [
                (
                    event["event"],
                    "yes" if event["payload"].get("success") else "no",
                    event["payload"].get("detail"),
                    json.dumps(
                        {
                            key: value
                            for key, value in event["payload"].items()
                            if key not in {"success", "detail"}
                        },
                        sort_keys=True,
                    ),
                )
                for event in observed
            ],
            colors={1: "success"},
        )
        errors = experiment_errors(report)
        fill_table(self.errors, [(item,) for item in errors] or [(tr("reports.no_errors"),)])
        fill_table(self.resources, self._resource_rows(report))
        # The UI renders its own localized view; the backend's English Markdown artifact is
        # what "Save Markdown" writes.
        self.rendered.setMarkdown(experiment_markdown(report))
        self.report_state.show_content()

    @staticmethod
    def _resource_rows(report: dict[str, object]) -> list[tuple[str, object]]:
        samples = [item for item in report.get("resource_statistics") or [] if item]  # type: ignore[union-attr]
        rss = [item.get("process_rss_bytes") for item in samples if item.get("process_rss_bytes")]
        available = [
            item.get("available_memory_bytes")
            for item in samples
            if item.get("available_memory_bytes") is not None
        ]
        capture = report.get("capture") or {}
        assert isinstance(capture, dict)
        return [
            (tr("reports.resources.samples"), len(samples)),
            (tr("reports.resources.peak_rss"), format_bytes(max(rss)) if rss else "—"),
            (tr("reports.resources.min_available"),
             format_bytes(min(available)) if available else "—"),
            (tr("capture.frames"), capture.get("frame_count")),
            (tr("capture.bytes"), format_bytes(capture.get("captured_bytes"))),
            (tr("capture.dropped"), capture.get("dropped_frames")),
            (tr("capture.truncated"), capture.get("truncated_frames")),
            (tr("capture.file"), capture.get("path")),
        ]

    def _save(self, kind: str) -> None:
        if self.report is None or self.experiment_id is None:
            return
        if kind == "json":
            path = self.context.ask_save(
                self, "reports.save.dialog", f"{self.experiment_id}.json", "json"
            )
            content = json.dumps(self.report, indent=2, sort_keys=True, ensure_ascii=False)
        else:
            path = self.context.ask_save(
                self, "reports.save.dialog", f"{self.experiment_id}.md", "markdown"
            )
            content = self.markdown
        if path is None:
            return
        try:
            path.write_text(content + ("\n" if not content.endswith("\n") else ""), "utf-8")
        except OSError as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.session.log(Msg("log.saved", kind=Msg("document.report"), path=path))

    def refresh_actions(self) -> None:
        self.refresh_button.setEnabled(self.session.connected)
        self.save_json.setEnabled(self.report is not None)
        self.save_markdown.setEnabled(bool(self.markdown))

    def activated(self, argument: object = None) -> None:
        if self.session.connected:
            self.refresh_list()
        if isinstance(argument, str):
            self.open_report(argument)

