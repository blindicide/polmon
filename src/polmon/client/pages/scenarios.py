"""Scenarios: browse, inspect, run and cancel experiments with live per-action status."""

from __future__ import annotations

import secrets
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from polmon.client import theme
from polmon.client.api import ApiClientError
from polmon.client.formatting import estimate_eta, format_seconds
from polmon.client.pages import Context, Page
from polmon.client.pages.topologies import MAX_DOCUMENT_BYTES, DocumentLibrary
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import StatusBadge, YamlEditor, fill_table, make_table, primary_button
from polmon.client.yamlmap import document_id, locate, reason_line

TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "error", "interrupted"}
# Consecutive status-poll failures tolerated (≈ 0.5 s apart) before the outcome is unknown.
MAX_POLL_FAILURES = 12


def new_experiment_id() -> str:
    return f"gui-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


class BackendLost(RuntimeError):
    pass


class ScenariosPage(Page):
    key = "scenarios"
    title = "Scenarios"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.path: Path | None = None
        self.result: dict[str, object] | None = None
        self.validated_source: str | None = None
        self.running_id: str | None = None
        self.last_record: dict[str, object] | None = None
        # Results of the last run, kept while the scenario text is unchanged, so background
        # re-validation (e.g. after a refresh) never wipes what the operator just saw.
        self.run_source: str | None = None
        self.run_statuses: dict[str, tuple[str, str]] = {}
        self.run_report: dict[str, object] | None = None
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.setInterval(700)
        self._auto.timeout.connect(lambda: self.validate(quiet=True))

        splitter = QSplitter()
        self.library = DocumentLibrary("Library", "scenarios", self)
        splitter.addWidget(self.library)

        centre = QWidget()
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.document_label = QLabel("Untitled scenario")
        self.badge = StatusBadge()
        header.addWidget(self.document_label, 1)
        header.addWidget(self.badge)
        centre_layout.addLayout(header)
        self.editor = YamlEditor()
        self.editor.textChanged.connect(self._edited)
        centre_layout.addWidget(self.editor, 1)
        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(lambda: self.validate(quiet=False))
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        centre_layout.addLayout(validate_row)
        splitter.addWidget(centre)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.summary = make_table(("Property", "Value"), stretch=1)
        self.sequence = make_table(
            ("#", "Action", "Kind", "Source → target", "Service", "Status", "Detail"), stretch=6
        )
        self.conditions = make_table(("Role", "Action", "Field", "Expected", "Outcome"), stretch=4)
        self.problems = make_table(("Line", "Location", "Problem"), stretch=2)
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._goto_problem)
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.sequence, "Sequence")
        self.tabs.addTab(self.conditions, "Conditions")
        self.tabs.addTab(self.problems, "Problems")
        right_layout.addWidget(self.tabs, 1)

        run_box = QGroupBox("Experiment")
        run_layout = QVBoxLayout(run_box)
        id_row = QHBoxLayout()
        id_row.addWidget(QLabel("Experiment ID"))
        self.experiment_id = QLineEdit(new_experiment_id())
        self.experiment_id.setMaxLength(64)
        regenerate = QPushButton("New ID")
        regenerate.clicked.connect(lambda: self.experiment_id.setText(new_experiment_id()))
        id_row.addWidget(self.experiment_id, 1)
        id_row.addWidget(regenerate)
        run_layout.addLayout(id_row)
        buttons = QHBoxLayout()
        self.run_button = primary_button("Run experiment")
        self.run_button.setToolTip("Run on the deployed required topology (Ctrl+R)")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Ask the backend to stop after the current action (Esc)")
        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.context.cancel_operation)
        self.outcome = StatusBadge()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.outcome)
        run_layout.addLayout(buttons)
        self.run_detail = QLabel("")
        self.run_detail.setObjectName("muted")
        self.run_detail.setWordWrap(True)
        run_layout.addWidget(self.run_detail)
        follow = QHBoxLayout()
        self.report_button = QPushButton("Open report")
        self.telemetry_button = QPushButton("Open telemetry")
        self.report_button.clicked.connect(
            lambda: self.context.navigate("reports", self._last_id())
        )
        self.telemetry_button.clicked.connect(
            lambda: self.context.navigate("telemetry", self._last_id())
        )
        follow.addWidget(self.report_button)
        follow.addWidget(self.telemetry_button)
        follow.addStretch(1)
        run_layout.addLayout(follow)
        right_layout.addWidget(run_box)
        splitter.addWidget(right)
        splitter.setSizes([200, 400, 520])
        splitter.setStretchFactor(2, 1)
        self.root.addWidget(splitter, 1)

        self.session.deployments_changed.connect(self._refresh_summary)
        self.session.topologies_changed.connect(lambda: self.validate(quiet=True))
        self.refresh_actions()

    # -- documents ----------------------------------------------------------------------------

    def open_dialog(self) -> None:
        path = self.context.ask_open(self, "Open scenario", "scenarios")
        if path is not None:
            self.open_path(path)

    def open_path(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                self.banner.show_message(
                    "Document too large", f"{path.name} exceeds the 2 MB document limit.", "danger"
                )
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.banner.show_problem(self.context.problem(error))
            return
        self.path = path
        self.editor.setPlainText(text)
        self.document_label.setText(path.name)
        self.document_label.setToolTip(str(path))
        self.session.log(f"Opened scenario {path}")
        self.validate(quiet=True)

    def source(self) -> str:
        return self.editor.toPlainText()

    def _edited(self) -> None:
        self.editor.set_error_line(None)
        if self.validated_source is not None and self.source() != self.validated_source:
            self.badge.set_status("modified")
        if self.session.connected and self.source().strip():
            self._auto.start()
        self.refresh_actions()

    # -- validation ---------------------------------------------------------------------------

    def validate(self, *, quiet: bool) -> None:
        source = self.source()
        if not source.strip() or self.running_id:
            return
        if not self.session.connected:
            if not quiet:
                self.banner.show_message(
                    "Not connected", "Connect to a backend to validate scenarios.", "warning"
                )
            return
        client = self.session.client()
        self.context.run(
            "Validate scenario",
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
        details = error.details if isinstance(error.details, dict) else {}
        rows = []
        errors = details.get("errors")
        if isinstance(errors, list):
            for item in errors:
                if isinstance(item, dict):
                    location = str(item.get("location") or "")
                    rows.append(
                        (locate(source, location), location or "document", item.get("message"))
                    )
        elif isinstance(details.get("reason"), str):
            reason = str(details["reason"])
            rows.append((reason_line(reason), "YAML syntax", reason.splitlines()[0]))
        else:
            rows.append((None, "document", str(error).split(": ", 1)[-1]))
        self.result = None
        self.validated_source = source
        fill_table(self.problems, rows)
        self.problems.resizeRowsToContents()
        self.tabs.setTabText(3, f"Problems ({len(rows)})")
        self.tabs.setCurrentWidget(self.problems)
        self.badge.set_status("invalid")
        self.editor.set_error_line(next((line for line, _, _ in rows if line), None))
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
        self.problems.setRowCount(0)
        self.tabs.setTabText(3, "Problems")
        if self.tabs.currentWidget() is self.problems:
            self.tabs.setCurrentWidget(self.summary)
        self._refresh_summary()
        if source == self.run_source and not self.running_id:
            self._fill_sequence(self.run_statuses)
            self._fill_conditions(self.run_report)
        elif not self.running_id:
            self._fill_sequence({})
            self._fill_conditions(None)
        self.refresh_actions()

    def _check(self) -> dict[str, object]:
        check = (self.result or {}).get("topology_check")
        return check if isinstance(check, dict) else {}

    def _refresh_summary(self) -> None:
        if not self.result:
            self.summary.setRowCount(0)
            self.badge.set_status("")
            return
        scenario = self.result.get("scenario") or {}
        assert isinstance(scenario, dict)
        check = self._check()
        required = str(check.get("topology_id") or scenario.get("required_topology"))
        deployed = self.session.deployed(required)
        problems = check.get("problems") or []
        if not check.get("loaded"):
            topology_state = "not loaded on the backend — load and deploy it first"
        elif problems:
            topology_state = "incompatible: " + "; ".join(str(item) for item in problems)
        elif not deployed:
            topology_state = "compatible, not deployed — deploy it before running"
        else:
            topology_state = "compatible and deployed"
        rows = [
            ("Scenario", scenario.get("id")),
            ("Required topology", required),
            ("Topology state", topology_state),
            ("Initial conditions", ", ".join(scenario.get("initial_conditions") or [])),
            ("Permitted actions", ", ".join(scenario.get("permitted_actions") or [])),
            ("Actions in sequence", len(scenario.get("sequence") or [])),
            ("Timeout", format_seconds(scenario.get("timeout_seconds"))),
            ("Cleanup policy", scenario.get("cleanup_policy")),
        ]
        fill_table(self.summary, rows)
        state_item = self.summary.item(2, 1)
        if state_item is not None:
            ready = topology_state == "compatible and deployed"
            state_item.setForeground(theme.color("success" if ready else "warning"))
        self.badge.set_status("valid" if not problems else "incompatible")
        self.refresh_actions()

    def _fill_sequence(self, statuses: dict[str, tuple[str, str]], current: str | None = None):
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
                    item["role"].replace("_", " "),
                    item["action"],
                    item["field"],
                    f"{item['expected']} (actual {item['actual']})",
                    item["outcome"].replace(" ", "_"),
                )
                for item in report["expected_vs_actual"]  # type: ignore[union-attr]
            ]
        else:
            scenario = (self.result or {}).get("scenario") or {}
            assert isinstance(scenario, dict)
            rows = [
                ("success requirement", item["action"], item["field"], item["equals"], "")
                for item in scenario.get("success_conditions") or []
            ] + [
                ("failure trigger", item["action"], item["field"], item["equals"], "")
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
                        raise BackendLost(
                            f"lost contact with the backend while experiment {experiment_id} "
                            "was running; its outcome is unknown until the backend is reachable "
                            "again"
                        ) from error
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
                detail = "cancelling" if status == "cancelling" else f"action {current or '—'}"
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
        self.session.active_experiment = experiment_id
        self.outcome.set_status("running")
        self.run_detail.setText(f"{experiment_id}: submitted")
        self._fill_sequence({})
        self._fill_conditions(None)
        self.tabs.setCurrentWidget(self.sequence)
        handle = self.context.run(
            f"Experiment {experiment_id}",
            work,
            on_success=self._finished,
            on_failure=self._failed,
            on_progress=self._progress,
            banner=self.banner,
            operation=True,
            on_cancel=lambda: self._request_cancel(experiment_id),
        )
        if handle is None:
            self.running_id = None
            self.session.active_experiment = None
        else:
            self.session.experiments_changed.emit()
        self.refresh_actions()

    def _request_cancel(self, experiment_id: str) -> None:
        client = self.session.client()
        self.run_detail.setText(f"{experiment_id}: cancellation requested…")
        self.outcome.set_status("cancelling")
        self.context.run(
            f"Cancel experiment {experiment_id}",
            lambda token, report: client.cancel_experiment(experiment_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def _progress(self, update: ProgressUpdate) -> None:
        record = update.payload if isinstance(update.payload, dict) else {}
        progress = record.get("progress") or {}
        current = progress.get("current_action") if isinstance(progress, dict) else None
        scenario = (self.result or {}).get("scenario") or {}
        sequence = scenario.get("sequence") or [] if isinstance(scenario, dict) else []
        statuses = {action["id"]: ("done", "") for action in sequence[: update.completed]}
        self._fill_sequence(statuses, current=current)
        self.run_detail.setText(
            f"{self.running_id}: {record.get('status')} · {update.completed}/{update.total} "
            f"actions · {format_seconds(update.elapsed)} elapsed"
        )

    def _finished(self, result: object) -> None:
        assert isinstance(result, dict)
        record = result["record"]
        report = result.get("report")
        self.last_record = record
        self.running_id = None
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
        errors = record.get("errors") or []
        failure = record.get("error")
        if isinstance(failure, dict):
            errors = [failure.get("message")]
        capture = record.get("capture") or {}
        self.run_detail.setText(
            f"{record.get('experiment_id')}: {status}"
            + (f" · {capture.get('frame_count')} frames captured" if capture else "")
            + (" · errors: " + "; ".join(str(item) for item in errors) if errors else "")
        )
        self.session.log(
            f"Experiment {record.get('experiment_id')} finished: {status}",
            "info" if status == "succeeded" else "warning",
        )
        self.experiment_id.setText(new_experiment_id())
        self.session.experiments_changed.emit()
        self.context.navigate("refresh")
        self.refresh_actions()

    def _failed(self, error: BaseException) -> None:
        experiment_id = self.running_id
        self.running_id = None
        self.session.active_experiment = None
        if isinstance(error, BackendLost):
            self.outcome.set_status("unknown")
            self.banner.show_message("Backend lost", str(error), "danger")
        else:
            self.outcome.set_status("error")
        self.run_detail.setText(f"{experiment_id}: {self.context.problem(error).title}")
        if experiment_id:
            self.last_record = {"experiment_id": experiment_id}
        self.experiment_id.setText(new_experiment_id())
        self.refresh_actions()

    def refresh_actions(self) -> None:
        running = self.running_id is not None
        self.validate_button.setEnabled(self.session.connected and bool(self.source().strip()))
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
