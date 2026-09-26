"""Reports: experiment list, overall status, expected vs actual, Markdown and JSON views."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from polmon.client.formatting import (
    duration_between,
    format_bytes,
    format_datetime,
    format_seconds,
)
from polmon.client.pages import Context, Page
from polmon.client.tasks import CancelToken
from polmon.client.widgets import (
    JsonTree,
    StatusBadge,
    cell_text,
    fill_table,
    make_table,
    muted,
)


class ReportsPage(Page):
    key = "reports"
    title = "Reports"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.report: dict[str, object] | None = None
        self.markdown = ""
        self.experiment_id: str | None = None

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(muted("Experiments on the backend (newest first)"), 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Reload the experiment list (F5)")
        self.refresh_button.clicked.connect(self.refresh_list)
        row.addWidget(self.refresh_button)
        left_layout.addLayout(row)
        self.list = make_table(
            ("Experiment", "Scenario", "Topology", "Status", "Started"), stretch=0
        )
        self.list.itemSelectionChanged.connect(self._chosen)
        left_layout.addWidget(self.list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header = QGroupBox("Report")
        grid = QGridLayout(header)
        self.status = StatusBadge()
        self.title_label = QLabel("Select an experiment")
        self.title_label.setObjectName("pageTitle")
        self.meta = muted()
        grid.addWidget(self.title_label, 0, 0)
        grid.addWidget(self.status, 0, 1)
        grid.addWidget(self.meta, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        save_row = QHBoxLayout()
        self.save_json = QPushButton("Save JSON…")
        self.save_markdown = QPushButton("Save Markdown…")
        self.save_json.clicked.connect(lambda: self._save("json"))
        self.save_markdown.clicked.connect(lambda: self._save("md"))
        save_row.addStretch(1)
        save_row.addWidget(self.save_json)
        save_row.addWidget(self.save_markdown)
        grid.addLayout(save_row, 2, 0, 1, 2)
        right_layout.addWidget(header)

        self.tabs = QTabWidget()
        self.comparison = make_table(
            ("Role", "Action", "Field", "Expected", "Actual", "Outcome"), stretch=0
        )
        self.observations = make_table(("Action", "Success", "Detail", "Data"), stretch=3)
        self.errors = make_table(("Error",), stretch=0)
        self.resources = make_table(("Statistic", "Value"), stretch=1)
        self.rendered = QTextBrowser()
        self.rendered.setOpenExternalLinks(False)
        self.json = JsonTree()
        self.tabs.addTab(self.comparison, "Expected vs actual")
        self.tabs.addTab(self.observations, "Observations")
        self.tabs.addTab(self.errors, "Errors")
        self.tabs.addTab(self.resources, "Resources && capture")
        self.tabs.addTab(self.rendered, "Report")
        self.tabs.addTab(self.json, "JSON")
        right_layout.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setSizes([520, 700])
        self.root.addWidget(splitter, 1)

        self.session.experiments_changed.connect(self._fill_list)
        self.refresh_actions()

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
        self.list.blockSignals(True)
        fill_table(self.list, rows, colors={3: "status"})
        for index, row in enumerate(rows):
            if row[0] == selected:
                self.list.selectRow(index)
        self.list.blockSignals(False)

    def _chosen(self) -> None:
        rows = self.list.selectionModel().selectedRows()
        if rows:
            item = self.list.item(rows[0].row(), 0)
            if item is not None and item.text() != self.experiment_id:
                self.open_report(item.text())

    def open_report(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        client = self.session.client()

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            return {
                "report": client.report(experiment_id),
                "markdown": client.report_markdown(experiment_id),
            }

        self.title_label.setText(experiment_id)
        self.meta.setText("Loading report…")
        self.context.run(
            f"Open report {experiment_id}",
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
            self.meta.setText("No report is available for this experiment.")
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
        self.markdown = str(result.get("markdown") or "")
        execution = report.get("execution") or {}
        scenario = report.get("scenario") or {}
        topology = report.get("topology") or {}
        assert isinstance(execution, dict) and isinstance(scenario, dict)
        assert isinstance(topology, dict)
        status = str(report.get("status"))
        self.status.set_status(status)
        duration = duration_between(execution.get("started_at"), execution.get("finished_at"))
        self.meta.setText(
            f"Scenario {scenario.get('id')} on topology {topology.get('id')} · started "
            f"{format_datetime(execution.get('started_at'))} · duration "
            f"{format_seconds(duration)} · cleanup "
            f"{'performed' if execution.get('cleanup_performed') else 'not performed'} · "
            f"polmon {report.get('polmon_version')}"
        )
        comparisons = report.get("expected_vs_actual") or []
        fill_table(
            self.comparison,
            [
                (
                    item["role"].replace("_", " "),
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
        )
        errors = report.get("errors") or []
        fill_table(self.errors, [(item,) for item in errors] or [("No errors recorded",)])
        self.tabs.setTabText(2, f"Errors ({len(errors)})" if errors else "Errors")
        fill_table(self.resources, self._resource_rows(report))
        self.rendered.setMarkdown(self.markdown)
        self.json.load(report)
        self.refresh_actions()

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
            ("Resource samples", len(samples)),
            ("Peak backend RSS", format_bytes(max(rss)) if rss else "—"),
            ("Minimum available memory", format_bytes(min(available)) if available else "—"),
            ("Frames captured", capture.get("frame_count")),
            ("Bytes captured", format_bytes(capture.get("captured_bytes"))),
            ("Frames dropped", capture.get("dropped_frames")),
            ("Frames truncated", capture.get("truncated_frames")),
            ("Capture file (on the backend)", capture.get("path")),
        ]

    def _save(self, kind: str) -> None:
        if self.report is None or self.experiment_id is None:
            return
        if kind == "json":
            path = self.context.ask_save(
                self, "Save report", f"{self.experiment_id}.json", "JSON (*.json)"
            )
            content = json.dumps(self.report, indent=2, sort_keys=True, ensure_ascii=False)
        else:
            path = self.context.ask_save(
                self, "Save report", f"{self.experiment_id}.md", "Markdown (*.md)"
            )
            content = self.markdown
        if path is None:
            return
        try:
            path.write_text(content + ("\n" if not content.endswith("\n") else ""), "utf-8")
        except OSError as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.session.log(f"Saved report to {path}")

    def refresh_actions(self) -> None:
        self.refresh_button.setEnabled(self.session.connected)
        self.save_json.setEnabled(self.report is not None)
        self.save_markdown.setEnabled(bool(self.markdown))

    def activated(self, argument: object = None) -> None:
        if self.session.connected:
            self.refresh_list()
        if isinstance(argument, str):
            self.open_report(argument)
