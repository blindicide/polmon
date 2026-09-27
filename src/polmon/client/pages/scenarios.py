"""Scenarios: browse, inspect, run and cancel experiments with live per-action status."""

from __future__ import annotations

import secrets
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSplitter, QTabWidget, QWidget

from polmon.client import theme
from polmon.client.api import ApiClientError
from polmon.client.errors import Problem, backend_message
from polmon.client.formatting import duration, estimate_eta, format_duration
from polmon.client.i18n import Joined, Msg, status_msg, tr
from polmon.client.pages import Context, Page, write_document
from polmon.client.pages.topologies import MAX_DOCUMENT_BYTES, DocumentLibrary, problem_rows
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import (
    RAW_ROLE,
    Card,
    StateView,
    StatusBadge,
    YamlEditor,
    accessible,
    button,
    cell_text,
    fill_table,
    label,
    make_table,
    monospace_font,
    primary_button,
    tint,
)
from polmon.client.yamlmap import document_id

TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "error", "interrupted"}
# Consecutive status-poll failures tolerated (≈ 0.5 s apart) before the outcome is unknown.
MAX_POLL_FAILURES = 12


def new_experiment_id() -> str:
    return f"gui-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


class BackendLost(RuntimeError):
    def __init__(self, experiment_id: str) -> None:
        super().__init__(f"lost contact with the backend while experiment {experiment_id} ran")
        self.experiment_id = experiment_id


def experiment_errors(record: dict[str, object]) -> list[object]:
    """Localized errors of an experiment record (coded when the backend sends codes)."""
    failure = record.get("error")
    if isinstance(failure, dict):
        return [
            backend_message(
                failure.get("message_code"), failure.get("params"), str(failure.get("message"))
            )
        ]
    details = record.get("error_details")
    if isinstance(details, list) and details:
        return [
            backend_message(item.get("message_code"), item.get("params"), str(item.get("message")))
            for item in details
            if isinstance(item, dict)
        ]
    return [
        backend_message(None, None, str(item)) for item in record.get("errors") or []  # type: ignore[union-attr]
    ]


class ScenariosPage(Page):
    key = "scenarios"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.path: Path | None = None
        self.document_name: str | None = None
        self.saved_source = ""
        self.result: dict[str, object] | None = None
        self.validated_source: str | None = None
        self.problem_rows: list[tuple[object, object, object]] = []
        self.running_id: str | None = None
        self.last_record: dict[str, object] | None = None
        self.run_line: Msg | str = ""
        # Results of the last run, kept while the scenario text is unchanged, so background
        # re-validation (e.g. after a refresh) never wipes what the operator just saw.
        self.run_source: str | None = None
        self.run_statuses: dict[str, tuple[str, object]] = {}
        self.run_report: dict[str, object] | None = None
        self.current_action: str | None = None
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.setInterval(700)
        self._auto.timeout.connect(lambda: self.validate(quiet=True))

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        self.library = DocumentLibrary("library.title", "scenarios", self)
        splitter.addWidget(self.library)

        editor_card = Card(name="editor")
        header = QHBoxLayout()
        self.document_label = QLabel()
        self.document_label.setObjectName("cardTitle")
        self.badge = StatusBadge()
        header.addWidget(self.document_label, 1)
        header.addWidget(self.badge)
        editor_card.body.addLayout(header)
        self.editor = YamlEditor()
        self.editor.setObjectName("scenarioEditor")
        editor_card.add(self.editor, 1)
        validate_row = QHBoxLayout()
        self.validate_button = button("editor.validate", tip="scenarios.validate.tip",
                                      name="validateButton")
        self.validate_button.clicked.connect(lambda: self.validate(quiet=False))
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        self.save_button = button("editor.save_as", "quiet", tip="editor.save_as.tip",
                                  name="saveAs")
        self.save_button.clicked.connect(self.save_as)
        validate_row.addWidget(self.save_button)
        editor_card.body.addLayout(validate_row)
        splitter.addWidget(editor_card)

        right = QSplitter(Qt.Orientation.Vertical)
        right.setChildrenCollapsible(False)
        inspect_card = Card("scenarios.inspection", name="inspection")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("scenarioTabs")
        self.summary = make_table(("column.property", "column.value"), stretch=1,
                                  sortable=False, name="scenarioSummary")
        self.sequence = make_table(
            (
                "column.number",
                "column.action",
                "column.kind",
                "column.source_target",
                "column.service",
                "column.status",
                "column.detail",
            ),
            stretch=6,
            mono=(1, 3),
            sortable=False,
            name="scenarioSequence",
        )
        self.conditions = make_table(
            ("column.role", "column.action", "column.field", "column.expected", "column.outcome"),
            stretch=3, mono=(1,), sortable=False, name="scenarioConditions",
        )
        self.problems = make_table(
            ("column.line", "column.location", "column.problem"), stretch=2, mono=(1,),
            name="scenarioProblems",
        )
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._goto_problem)
        for widget in (self.summary, self.sequence, self.conditions, self.problems):
            self.tabs.addTab(widget, "")
        self.inspect_state = StateView(self.tabs)
        inspect_card.add(self.inspect_state, 1)
        right.addWidget(inspect_card)

        run_card = Card("scenarios.run", name="run")
        self.outcome = StatusBadge()
        run_card.add_action(self.outcome)
        id_row = QHBoxLayout()
        id_row.addWidget(label("scenarios.experiment_id", name="fieldLabel"))
        self.experiment_id = QLineEdit(new_experiment_id())
        self.experiment_id.setObjectName("experimentId")
        accessible(self.experiment_id, "a11y.experiment_id")
        self.experiment_id.setFont(monospace_font())
        self.experiment_id.setMaxLength(64)
        regenerate = button("scenarios.new_id", "quiet", tip="scenarios.new_id.tip",
                            name="newId")
        regenerate.clicked.connect(lambda: self.experiment_id.setText(new_experiment_id()))
        id_row.addWidget(self.experiment_id, 1)
        id_row.addWidget(regenerate)
        run_card.body.addLayout(id_row)
        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE["sm"])
        self.deploy_required = button(
            "scenarios.deploy_required", tip="scenarios.deploy_required.tip",
            name="deployRequired",
        )
        self.deploy_required.clicked.connect(self._deploy_required)
        self.deploy_required.hide()
        self.run_button = primary_button("scenarios.run.button", tip="scenarios.run.tip",
                                         name="runButton")
        self.cancel_button = button("common.cancel", tip="scenarios.cancel.tip",
                                    name="cancelButton")
        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.context.cancel_operation)
        buttons.addWidget(self.deploy_required)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        self.report_button = button("scenarios.open_report", "quiet", name="openReport")
        self.telemetry_button = button("scenarios.open_telemetry", "quiet", name="openTelemetry")
        self.report_button.clicked.connect(
            lambda: self.context.navigate("reports", self._last_id())
        )
        self.telemetry_button.clicked.connect(
            lambda: self.context.navigate("telemetry", self._last_id())
        )
        run_card.body.addLayout(buttons)
        follow = QHBoxLayout()
        follow.addWidget(self.report_button)
        follow.addWidget(self.telemetry_button)
        follow.addStretch(1)
        self.run_detail = label(name="muted", wrap=True)
        self.run_detail.setObjectName("runDetail")
        run_card.add(self.run_detail)
        run_card.body.addLayout(follow)
        right.addWidget(run_card)
        right.setSizes([520, 170])
        splitter.addWidget(right)
        splitter.setSizes([190, 400, 660])
        for index, factor in enumerate((0, 2, 3)):
            splitter.setStretchFactor(index, factor)
        self.root.addWidget(splitter, 1)

        self.session.deployments_changed.connect(self._refresh_summary)
        self.session.topologies_changed.connect(lambda: self.validate(quiet=True))
        self.retranslate()
        self.refresh_actions()
        # Connected last: the editor signals while the page is still being built.
        self.editor.textChanged.connect(self._edited)

    def retranslate(self) -> None:
        count = len(self.problem_rows)
        titles = (
            tr("scenarios.tab.summary"),
            tr("scenarios.tab.sequence"),
            tr("scenarios.tab.conditions"),
            tr("editor.tab.problems_count", count=count) if count else tr("editor.tab.problems"),
        )
        for index, title in enumerate(titles):
            self.tabs.setTabText(index, title)
        self._update_label()
        self._refresh_summary()
        if self.result:
            if self.running_id:
                self._fill_sequence(self.run_statuses, current=self.current_action)
            else:
                self._fill_sequence(self.run_statuses if self.run_source == self.source() else {})
            self._fill_conditions(self.run_report)
        if self.problem_rows:
            fill_table(self.problems, self.problem_rows)
        self.run_detail.setText(str(self.run_line))
        self._update_state()

    def _update_state(self) -> None:
        if self.result or self.problem_rows:
            self.inspect_state.show_content()
        elif self.source().strip():
            self.inspect_state.show_empty(Msg("scenarios.not_validated"),
                                          Msg("scenarios.not_validated_hint"))
        else:
            self.inspect_state.show_empty(Msg("scenarios.no_document"),
                                          Msg("scenarios.no_document_hint"))

    def _set_run_line(self, line: Msg | str) -> None:
        self.run_line = line
        self.run_detail.setText(str(line))

    # -- documents ----------------------------------------------------------------------------

    def open_dialog(self) -> None:
        path = self.context.ask_open(self, "scenarios.open.dialog", "scenarios")
        if path is not None:
            self.open_path(path)

    def open_path(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                self.banner.show_message(
                    Msg("problem.too_large.title"),
                    Msg("editor.too_large", name=path.name),
                    "danger",
                )
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.path = path
        self.document_name = path.name
        self.saved_source = text
        self.editor.setPlainText(text)
        self._update_label()
        self.session.log(Msg("log.opened", kind=Msg("document.scenario"), path=path))
        self.validate(quiet=True)

    def source(self) -> str:
        return self.editor.toPlainText()

    def save(self) -> None:
        """Save to the opened file (Ctrl+S); ask for a path when there is none."""
        if self.path is None:
            self.save_as()
        elif write_document(self, self.path, self.source(), "scenario"):
            self.saved_source = self.source()
            self._update_label()

    def save_as(self) -> None:
        suggested = (
            self.path.name if self.path else f"{document_id(self.source()) or 'scenario'}.yml"
        )
        path = self.context.ask_save(self, "scenarios.save.dialog", suggested, "yaml")
        if path is not None and write_document(self, path, self.source(), "scenario"):
            self.path = path
            self.document_name = path.name
            self.saved_source = self.source()
            self._update_label()

    def _update_label(self) -> None:
        name = self.path.name if self.path else self.document_name
        dirty = self.path is not None and self.source() != self.saved_source
        text = name or tr("scenarios.untitled")
        self.document_label.setText(f"{text} •" if dirty else text)
        self.document_label.setToolTip(tr("editor.unsaved") if dirty else str(self.path or text))

    def _edited(self) -> None:
        self.editor.set_error_line(None)
        if self.path is not None:
            self._update_label()
        if self.validated_source is not None and self.source() != self.validated_source:
            self.badge.set_status("modified")
        if self.session.connected and self.source().strip():
            self._auto.start()
        self._update_state()
        self.refresh_actions()

    # -- validation ---------------------------------------------------------------------------

    def validate(self, *, quiet: bool) -> None:
        source = self.source()
        if not source.strip() or self.running_id:
            return
        if not self.session.connected:
            if not quiet:
                self.banner.show_message(
                    Msg("common.not_connected"), Msg("scenarios.validate.offline"), "warning"
                )
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.validate_scenario"),
            lambda token, report: client.validate_scenario(source),
            on_success=lambda result: self._show_result(source, result),  # type: ignore[arg-type]
            on_failure=lambda error: self._show_failure(source, error),
            banner=None if quiet else self.banner,
            quiet=quiet,
        )

    def _show_failure(self, source: str, error: BaseException) -> None:
        if source != self.source() or not isinstance(error, ApiClientError):
            return
        if error.status != 422:
            return
        rows = problem_rows(source, error)
        self.result = None
        self.validated_source = source
        self.problem_rows = rows
        fill_table(self.problems, rows)
        self.problems.resizeRowsToContents()
        self.retranslate()
        self.tabs.setCurrentWidget(self.problems)
        self.badge.set_status("invalid")
        self.editor.set_error_line(
            next((line for line, _, _ in rows if isinstance(line, int)), None)
        )
        self.refresh_actions()

    def _goto_problem(self, item) -> None:  # noqa: ANN001
        cell = self.problems.item(item.row(), 0)
        if cell is not None and cell.text().isdigit():
            self.editor.goto_line(int(cell.text()))
            self.editor.set_error_line(int(cell.text()))

    def _show_result(self, source: str, result: dict[str, object]) -> None:
        if source != self.source():
            return
        self.result = result
        self.validated_source = source
        self.problem_rows = []
        self.problems.setRowCount(0)
        if self.tabs.currentWidget() is self.problems:
            self.tabs.setCurrentWidget(self.summary)
        if source != self.run_source and not self.running_id:
            self.run_statuses, self.run_report = {}, None
        self.retranslate()
        self.refresh_actions()

    def _check(self) -> dict[str, object]:
        check = (self.result or {}).get("topology_check")
        return check if isinstance(check, dict) else {}

    def _refresh_summary(self) -> None:
        if not self.result:
            self.summary.setRowCount(0)
            if not self.problem_rows:
                self.badge.set_status("")
            return
        scenario = self.result.get("scenario") or {}
        assert isinstance(scenario, dict)
        check = self._check()
        required = str(check.get("topology_id") or scenario.get("required_topology"))
        deployed = self.session.deployed(required)
        problems = check.get("problems") or []
        if not check.get("loaded"):
            state, tone = tr("scenarios.state.not_loaded"), "warning"
        elif problems:
            state = tr(
                "scenarios.state.incompatible",
                problems="; ".join(str(item) for item in problems),
            )
            tone = "danger"
        elif not deployed:
            state, tone = tr("scenarios.state.not_deployed"), "warning"
        else:
            state, tone = tr("scenarios.state.ready"), "success"
        rows = [
            ("summary.scenario", scenario.get("id")),
            ("summary.required_topology", required),
            ("summary.topology_state", f"{theme.STATUS_GLYPHS[tone]} {state}"),
            ("summary.initial_conditions", ", ".join(scenario.get("initial_conditions") or [])),
            ("summary.permitted_actions", ", ".join(scenario.get("permitted_actions") or [])),
            ("summary.actions", len(scenario.get("sequence") or [])),
            ("summary.timeout", format_duration(scenario.get("timeout_seconds"))),
            ("summary.cleanup", scenario.get("cleanup_policy")),
        ]
        fill_table(self.summary, [(tr(key), value) for key, value in rows])
        state_item = self.summary.item(2, 1)
        if state_item is not None:
            tint(state_item, tone)
            state_item.setData(RAW_ROLE, tone)
        self.badge.set_status("valid" if not problems else "incompatible")
        self.refresh_actions()

    def _fill_sequence(
        self, statuses: dict[str, tuple[str, object]], current: str | None = None
    ) -> None:
        scenario = (self.result or {}).get("scenario") or {}
        assert isinstance(scenario, dict)
        rows = []
        for index, action in enumerate(scenario.get("sequence") or [], start=1):
            status, detail = statuses.get(action["id"], ("pending", ""))
            if action["id"] == current and status == "pending":
                status = "running"
            rows.append(
                (
                    index,
                    action["id"],
                    action["kind"],
                    f"{action['source']} → {action['target']}",
                    action.get("service"),
                    status,
                    detail,
                )
            )
        fill_table(self.sequence, rows, colors={5: "status"})

    def _fill_conditions(self, report: dict[str, object] | None) -> None:
        if report and isinstance(report.get("expected_vs_actual"), list):
            rows = [
                (
                    tr(f"condition.role.{item['role']}"),
                    item["action"],
                    item["field"],
                    tr("condition.expected_actual", expected=cell_text(item["expected"]),
                       actual=cell_text(item["actual"])),
                    item["outcome"].replace(" ", "_"),
                )
                for item in report["expected_vs_actual"]  # type: ignore[union-attr]
            ]
        else:
            scenario = (self.result or {}).get("scenario") or {}
            assert isinstance(scenario, dict)
            rows = [
                (tr("condition.role.success_requirement"), item["action"], item["field"],
                 cell_text(item["equals"]), "")
                for item in scenario.get("success_conditions") or []
            ] + [
                (tr("condition.role.failure_trigger"), item["action"], item["field"],
                 item["equals"], "")
                for item in scenario.get("failure_conditions") or []
            ]
        fill_table(self.conditions, rows, colors={4: "outcome"})

    # -- execution ----------------------------------------------------------------------------

    def _last_id(self) -> str | None:
        return self.running_id or (
            str(self.last_record.get("experiment_id")) if self.last_record else None
        )

    def ready(self) -> bool:
        check = self._check()
        return bool(
            self.result
            and self.session.connected
            and check.get("compatible")
            and self.session.deployed(str(check.get("topology_id")))
            and self.source() == self.validated_source
        )

    def run(self) -> None:
        if not self.ready() or self.context.busy:
            return
        experiment_id = self.experiment_id.text().strip()
        topology_id = str(self._check().get("topology_id"))
        source = self.source()
        client = self.session.client()
        scenario = (self.result or {}).get("scenario") or {}
        total = len(scenario.get("sequence") or []) if isinstance(scenario, dict) else 0

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            started = time.monotonic()
            record = client.run_experiment(experiment_id, topology_id, source, wait=False)
            failures = 0
            while str(record.get("status")) not in TERMINAL:
                token.sleep(0.4)
                try:
                    record = client.experiment(experiment_id)
                    failures = 0
                except ApiClientError as error:
                    if error.status is not None:
                        raise
                    failures += 1
                    if failures >= MAX_POLL_FAILURES:
                        raise BackendLost(experiment_id) from error
                    continue
                progress = record.get("progress") or {}
                done = int(progress.get("completed_actions") or 0)
                elapsed = time.monotonic() - started
                eta = estimate_eta(done, total, elapsed)
                timeout = progress.get("timeout_seconds")
                if isinstance(timeout, int | float):
                    remaining = max(0.0, float(timeout) - elapsed)
                    eta = remaining if eta is None else min(eta, remaining)
                current = progress.get("current_action")
                status = str(record.get("status"))
                detail = (
                    tr("scenarios.progress.cancelling")
                    if status == "cancelling"
                    else tr("scenarios.progress.action", action=current or "—")
                )
                report(ProgressUpdate(done, total, detail, elapsed, eta, record))
            report_document = None
            if record.get("status") not in {"error", "interrupted"}:
                try:
                    report_document = client.report(experiment_id)
                except ApiClientError:
                    report_document = None
            return {"record": record, "report": report_document}

        self.running_id = experiment_id
        self.run_source = source
        self.run_statuses = {}
        self.run_report = None
        self.current_action = None
        self.session.active_experiment = experiment_id
        self.outcome.set_status("running")
        self._set_run_line(Msg("scenarios.submitted", experiment=experiment_id))
        self._fill_sequence({})
        self._fill_conditions(None)
        self.tabs.setCurrentWidget(self.sequence)
        handle = self.context.run(
            Msg("operation.experiment", experiment=experiment_id),
            work,
            on_success=self._finished,
            on_failure=self._failed,
            on_progress=self._progress,
            banner=self.banner,
            operation=True,
            on_cancel=lambda: self._request_cancel(experiment_id),
            kind="experiment",
        )
        if handle is None:
            self.running_id = None
            self.session.active_experiment = None
        else:
            self.session.experiments_changed.emit()
        self.refresh_actions()

    def _request_cancel(self, experiment_id: str) -> None:
        client = self.session.client()
        self._set_run_line(Msg("scenarios.cancel_requested", experiment=experiment_id))
        self.outcome.set_status("cancelling")
        self.context.run(
            Msg("operation.cancel_experiment", experiment=experiment_id),
            lambda token, report: client.cancel_experiment(experiment_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def _progress(self, update: ProgressUpdate) -> None:
        record = update.payload if isinstance(update.payload, dict) else {}
        progress = record.get("progress") or {}
        current = progress.get("current_action") if isinstance(progress, dict) else None
        scenario = (self.result or {}).get("scenario") or {}
        sequence = (scenario.get("sequence") or []) if isinstance(scenario, dict) else []
        self.run_statuses = {action["id"]: ("done", "") for action in sequence[: update.completed]}
        self.current_action = current
        self._fill_sequence(self.run_statuses, current=current)
        self._set_run_line(
            Msg(
                "scenarios.progress_line",
                experiment=self.running_id,
                status=status_msg(record.get("status")),
                completed=update.completed,
                total=update.total,
                elapsed=duration(update.elapsed),
            )
        )

    def _finished(self, result: object) -> None:
        assert isinstance(result, dict)
        record = result["record"]
        report = result.get("report")
        self.last_record = record
        self.running_id = None
        self.current_action = None
        self.session.active_experiment = None
        status = str(record.get("status"))
        self.outcome.set_status(status)
        statuses = {
            item["action_id"]: ("ok" if item["success"] else "failed", item["detail"])
            for item in record.get("observations") or []
        }
        self.run_statuses = statuses
        self.run_report = report if isinstance(report, dict) else None
        self._fill_sequence(statuses)
        self._fill_conditions(self.run_report)
        errors = experiment_errors(record)
        capture = record.get("capture") or {}
        experiment = record.get("experiment_id")
        parts: list[object] = [Msg("scenarios.finished_line", experiment=experiment,
                                   status=status_msg(status))]
        if capture:
            parts.append(Msg("count.frames_captured", count=int(capture.get("frame_count") or 0)))
        if errors:
            parts.append(Msg("scenarios.errors", errors="; ".join(str(item) for item in errors)))
        self._set_run_line(Joined(parts))
        self.session.log(
            Msg("log.experiment_finished", experiment=experiment, status=status_msg(status)),
            "info" if status == "succeeded" else "warning",
        )
        self.context.notify(
            Msg("notify.experiment", experiment=experiment, status=status_msg(status)),
            "success" if status == "succeeded" else "warning",
        )
        self.experiment_id.setText(new_experiment_id())
        self.session.experiments_changed.emit()
        self.context.navigate("refresh")
        self.refresh_actions()

    def _failed(self, error: BaseException) -> None:
        experiment_id = self.running_id
        self.running_id = None
        self.current_action = None
        self.session.active_experiment = None
        if isinstance(error, BackendLost):
            self.outcome.set_status("unknown")
            self.banner.show_problem(
                Problem("scenarios.lost", Msg("scenarios.lost.detail",
                                              experiment=error.experiment_id)),
                "danger",
            )
        else:
            self.outcome.set_status("error")
        problem = self.context.problem(error) if not isinstance(error, BackendLost) else None
        self._set_run_line(
            Msg("scenarios.failed_line", experiment=experiment_id,
                problem=problem.title if problem else tr("scenarios.lost.title"))
        )
        if experiment_id:
            self.last_record = {"experiment_id": experiment_id}
        self.experiment_id.setText(new_experiment_id())
        self.refresh_actions()

    def _deploy_required(self) -> None:
        topology_id = str(self._check().get("topology_id") or "")
        if topology_id:
            self.context.navigate("deployment", {"deploy_topology": topology_id})

    def refresh_actions(self) -> None:
        running = self.running_id is not None
        check = self._check()
        needs_deploy = bool(
            self.result
            and check.get("compatible")
            and not self.session.deployed(str(check.get("topology_id")))
        )
        self.deploy_required.setVisible(needs_deploy and self.session.connected)
        self.deploy_required.setEnabled(needs_deploy and not self.context.busy)
        self.validate_button.setEnabled(self.session.connected and bool(self.source().strip()))
        self.save_button.setEnabled(bool(self.source().strip()))
        self.run_button.setEnabled(self.ready() and not self.context.busy)
        self.cancel_button.setEnabled(running)
        has_last = self._last_id() is not None
        self.report_button.setEnabled(has_last and not running)
        self.telemetry_button.setEnabled(has_last)
        self.experiment_id.setEnabled(not running)
        self.editor.setReadOnly(running)

    def activated(self, argument: object = None) -> None:
        if isinstance(argument, Path):
            self.open_path(argument)
        elif not self.source().strip() and document_id(self.source()) is None:
            self.editor.setFocus()

