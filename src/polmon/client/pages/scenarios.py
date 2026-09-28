"""Scenarios: browse, inspect, run and cancel experiments with live per-action status."""

from __future__ import annotations

import secrets
import time
from datetime import datetime
from pathlib import Path

import yaml
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

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



# The sequence table: status right after the number, so a run's progress is always in view.
SEQUENCE_COLUMNS = (
    "column.number",
    "column.status",
    "column.action",
    "column.kind",
    "column.source_target",
    "column.service",
    "column.detail",
)
STATUS_COLUMN = SEQUENCE_COLUMNS.index("column.status")
ACTION_COLUMN = SEQUENCE_COLUMNS.index("column.action")
SERVICE_COLUMN = SEQUENCE_COLUMNS.index("column.service")

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


class ScenarioStepEditor(QWidget):
    """Small offline-safe step-list editor backed by the canonical YAML document."""

    source_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._document: dict[str, object] | None = None
        self._loading = False
        root = QVBoxLayout(self)
        options = QFormLayout()
        self.scope = QComboBox()
        self.scope.setObjectName("scenarioStepScope")
        self.scope.addItem(tr("scenarios.step.sequence"), "sequence")
        self.scope.addItem(tr("scenarios.step.cleanup"), "cleanup")
        self.initial_conditions = QLineEdit()
        self.initial_conditions.setObjectName("scenarioInitialConditions")
        self.timeout = QDoubleSpinBox()
        self.timeout.setObjectName("scenarioTimeout")
        self.timeout.setRange(0.1, 3600.0)
        self.timeout.setDecimals(1)
        self.timeout.setValue(60.0)
        self.cleanup_policy = QComboBox()
        self.cleanup_policy.setObjectName("scenarioCleanupPolicy")
        for value in ("always", "on_failure", "never"):
            self.cleanup_policy.addItem(value, value)
        options.addRow(label("scenarios.step.scope"), self.scope)
        options.addRow(label("scenarios.options.initial_conditions"), self.initial_conditions)
        options.addRow(label("scenarios.options.timeout"), self.timeout)
        options.addRow(label("scenarios.options.cleanup_policy"), self.cleanup_policy)
        root.addLayout(options)
        self.steps = QListWidget()
        self.steps.setObjectName("scenarioSteps")
        self.steps.currentRowChanged.connect(self._selected)
        root.addWidget(self.steps, 2)
        actions = QHBoxLayout()
        for key, callback, name in (
            ("scenarios.step.add", self.add_step, "addStep"),
            ("scenarios.step.duplicate", self.duplicate_step, "duplicateStep"),
            ("scenarios.step.remove", self.remove_step, "removeStep"),
            ("scenarios.step.up", self.move_up, "moveStepUp"),
            ("scenarios.step.down", self.move_down, "moveStepDown"),
        ):
            control = button(key, "quiet", name=name)
            control.clicked.connect(callback)
            actions.addWidget(control)
        actions.addStretch(1)
        root.addLayout(actions)

        form = QFormLayout()
        self.step_id = QLineEdit()
        self.step_id.setObjectName("scenarioStepId")
        self.kind = QComboBox()
        self.kind.setObjectName("scenarioStepKind")
        for value in ("icmp_probe", "tcp_probe", "ssh_exec", "wait"):
            self.kind.addItem(value, value)
        self.source = QLineEdit()
        self.source.setObjectName("scenarioStepSource")
        self.target = QLineEdit()
        self.target.setObjectName("scenarioStepTarget")
        self.service = QLineEdit()
        self.service.setObjectName("scenarioStepService")
        self.command = QLineEdit()
        self.command.setObjectName("scenarioStepCommand")
        self.parameters = QLineEdit()
        self.parameters.setObjectName("scenarioStepParameters")
        self.expected_exit = QSpinBox()
        self.expected_exit.setObjectName("scenarioStepExpectedExit")
        self.expected_exit.setRange(0, 255)
        self.seconds = QDoubleSpinBox()
        self.seconds.setObjectName("scenarioStepSeconds")
        self.seconds.setRange(0.1, 60.0)
        self.seconds.setDecimals(2)
        self.seconds.setValue(1.0)
        for key, field in (
            ("scenarios.step.id", self.step_id),
            ("scenarios.step.kind", self.kind),
            ("scenarios.step.source", self.source),
            ("scenarios.step.target", self.target),
            ("scenarios.step.service", self.service),
            ("scenarios.step.command", self.command),
            ("scenarios.step.parameters", self.parameters),
            ("scenarios.step.expected_exit", self.expected_exit),
            ("scenarios.step.seconds", self.seconds),
        ):
            form.addRow(label(key), field)
        root.addLayout(form)
        self.step_id.editingFinished.connect(self._apply)
        self.source.editingFinished.connect(self._apply)
        self.target.editingFinished.connect(self._apply)
        self.service.editingFinished.connect(self._apply)
        self.command.editingFinished.connect(self._apply)
        self.parameters.editingFinished.connect(self._apply)
        self.expected_exit.valueChanged.connect(lambda _: self._apply())
        self.seconds.valueChanged.connect(lambda _: self._apply())
        self.kind.currentIndexChanged.connect(lambda _: self._apply())
        self.scope.currentIndexChanged.connect(lambda _: self._refresh())
        self.initial_conditions.editingFinished.connect(self._apply_options)
        self.timeout.valueChanged.connect(lambda _: self._apply_options())
        self.cleanup_policy.currentIndexChanged.connect(lambda _: self._apply_options())

    def retranslate(self) -> None:
        self.scope.setItemText(0, tr("scenarios.step.sequence"))
        self.scope.setItemText(1, tr("scenarios.step.cleanup"))

    def set_source(self, source: str) -> None:
        try:
            document = yaml.safe_load(source)
        except yaml.YAMLError:
            document = None
        self._document = document if isinstance(document, dict) else None
        self._refresh()
        self._refresh_options()

    def _emit_source(self) -> None:
        if self._document is not None:
            self.source_changed.emit(
                yaml.safe_dump(self._document, sort_keys=False, allow_unicode=True)
            )

    def _sequence(self) -> list[dict[str, object]]:
        if self._document is None:
            return []
        key = "cleanup" if self.scope.currentData() == "cleanup" else "sequence"
        sequence = self._document.setdefault(key, [])
        return sequence if isinstance(sequence, list) else []

    def _refresh_options(self) -> None:
        if self._document is None:
            return
        self._loading = True
        conditions = self._document.get("initial_conditions") or []
        self.initial_conditions.setText(", ".join(str(item) for item in conditions))
        self.timeout.setValue(float(self._document.get("timeout_seconds", 60.0)))
        index = self.cleanup_policy.findData(self._document.get("cleanup_policy", "always"))
        self.cleanup_policy.setCurrentIndex(max(0, index))
        self._loading = False

    def _apply_options(self) -> None:
        if self._loading or self._document is None:
            return
        self._document["initial_conditions"] = [
            item.strip() for item in self.initial_conditions.text().split(",") if item.strip()
        ]
        self._document["timeout_seconds"] = self.timeout.value()
        self._document["cleanup_policy"] = self.cleanup_policy.currentData()
        self._emit_source()

    def _refresh(self) -> None:
        row = self.steps.currentRow()
        self._loading = True
        self.steps.clear()
        for step in self._sequence():
            if isinstance(step, dict):
                item = QListWidgetItem(f"{step.get('id', '')} · {step.get('kind', '')}")
                self.steps.addItem(item)
        self._loading = False
        if self.steps.count():
            self.steps.setCurrentRow(min(max(row, 0), self.steps.count() - 1))
        self._selected(self.steps.currentRow())

    def _selected(self, row: int) -> None:
        if self._loading or row < 0:
            return
        sequence = self._sequence()
        if row >= len(sequence) or not isinstance(sequence[row], dict):
            return
        step = sequence[row]
        self._loading = True
        self.step_id.setText(str(step.get("id", "")))
        index = self.kind.findData(step.get("kind", "wait"))
        self.kind.setCurrentIndex(max(0, index))
        self.source.setText(str(step.get("source", "")))
        self.target.setText(str(step.get("target", "")))
        self.service.setText(str(step.get("service", "")))
        self.command.setText(str(step.get("command", "")))
        parameters = step.get("parameters")
        self.parameters.setText(
            yaml.safe_dump(parameters, default_flow_style=True, sort_keys=False).strip()
            if isinstance(parameters, dict)
            else ""
        )
        self.expected_exit.setValue(int(step.get("expected_exit_status", 0)))
        self.seconds.setValue(float(step.get("seconds", 1.0)))
        self._loading = False

    def _apply(self) -> None:
        if self._loading:
            return
        row = self.steps.currentRow()
        sequence = self._sequence()
        if row < 0 or row >= len(sequence) or not isinstance(sequence[row], dict):
            return
        step = sequence[row]
        kind = str(self.kind.currentData())
        parameters: object = {}
        if self.parameters.text().strip():
            try:
                parameters = yaml.safe_load(self.parameters.text())
            except yaml.YAMLError:
                return
            if not isinstance(parameters, dict):
                return
        step.clear()
        step.update({"id": self.step_id.text().strip(), "kind": kind})
        if kind == "wait":
            step["seconds"] = self.seconds.value()
        else:
            if self.source.text().strip():
                step["source"] = self.source.text().strip()
            if self.target.text().strip():
                step["target"] = self.target.text().strip()
            if kind == "tcp_probe" and self.service.text().strip():
                step["service"] = self.service.text().strip()
            if kind == "ssh_exec" and self.command.text().strip():
                step["command"] = self.command.text().strip()
                step["expected_exit_status"] = self.expected_exit.value()
            if parameters:
                step["parameters"] = parameters
        self._refresh()
        self._emit_source()

    def add_step(self) -> None:
        if self._document is None:
            return
        sequence = self._sequence()
        existing = {str(item.get("id")) for item in sequence if isinstance(item, dict)}
        index = 1
        while f"step-{index}" in existing:
            index += 1
        sequence.append({"id": f"step-{index}", "kind": "wait", "seconds": 1.0})
        self._refresh()
        self.steps.setCurrentRow(len(sequence) - 1)
        self._emit_source()

    def duplicate_step(self) -> None:
        row = self.steps.currentRow()
        sequence = self._sequence()
        if row < 0 or row >= len(sequence) or not isinstance(sequence[row], dict):
            return
        copy = dict(sequence[row])
        copy["id"] = f"{copy.get('id', 'step')}-copy"
        sequence.insert(row + 1, copy)
        self._refresh()
        self.steps.setCurrentRow(row + 1)
        self._emit_source()

    def remove_step(self) -> None:
        row = self.steps.currentRow()
        sequence = self._sequence()
        if 0 <= row < len(sequence):
            sequence.pop(row)
            self._refresh()
            self._emit_source()

    def _move(self, delta: int) -> None:
        row = self.steps.currentRow()
        sequence = self._sequence()
        target = row + delta
        if 0 <= row < len(sequence) and 0 <= target < len(sequence):
            sequence[row], sequence[target] = sequence[target], sequence[row]
            self._refresh()
            self.steps.setCurrentRow(target)
            self._emit_source()

    def move_up(self) -> None:
        self._move(-1)

    def move_down(self) -> None:
        self._move(1)


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
        self.step_editor = ScenarioStepEditor()
        self.step_editor.setObjectName("scenarioStepEditor")
        self.document_tabs = QTabWidget()
        self.document_tabs.setObjectName("scenarioDocumentTabs")
        self.document_tabs.addTab(self.editor, tr("scenarios.tab.yaml"))
        self.document_tabs.addTab(self.step_editor, tr("scenarios.tab.steps"))
        editor_card.add(self.document_tabs, 1)
        validate_row = QHBoxLayout()
        self.validate_button = button("editor.validate", tip="scenarios.validate.tip",
                                      name="validateButton")
        self.validate_button.clicked.connect(lambda: self.validate(quiet=False))
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        self.backend_scenarios = QComboBox()
        self.backend_scenarios.setObjectName("scenarioBackendLibrary")
        self.backend_refresh = button(
            "scenarios.backend_refresh", "quiet", name="refreshScenarios"
        )
        self.backend_refresh.clicked.connect(self.refresh_backend_library)
        self.backend_load = button("scenarios.backend_load", "quiet", name="loadScenario")
        self.backend_load.clicked.connect(self.load_from_backend)
        self.save_button = button("editor.save_as", "quiet", tip="editor.save_as.tip",
                                  name="saveAs")
        self.save_button.clicked.connect(self.save_as)
        validate_row.addWidget(self.save_button)
        self.save_backend = button(
            "scenarios.save_backend", "quiet", tip="scenarios.save_backend.tip",
            name="saveScenarioBackend"
        )
        self.save_backend.clicked.connect(self.save_to_backend)
        validate_row.addWidget(self.save_backend)
        editor_card.body.addLayout(validate_row)
        backend_row = QHBoxLayout()
        backend_row.addWidget(label("scenarios.backend_library"))
        self.backend_scenarios.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        accessible(self.backend_scenarios, "a11y.scenario_library")
        backend_row.addWidget(self.backend_scenarios, 1)
        backend_row.addWidget(self.backend_refresh)
        backend_row.addWidget(self.backend_load)
        editor_card.body.addLayout(backend_row)
        splitter.addWidget(editor_card)

        right = QSplitter(Qt.Orientation.Vertical)
        right.setChildrenCollapsible(False)
        inspect_card = Card("scenarios.inspection", name="inspection")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("scenarioTabs")
        self.summary = make_table(("column.property", "column.value"), stretch=1,
                                  sortable=False, name="scenarioSummary")
        self.sequence = make_table(
            SEQUENCE_COLUMNS,
            stretch=SEQUENCE_COLUMNS.index("column.detail"),
            mono=(ACTION_COLUMN, SEQUENCE_COLUMNS.index("column.source_target")),
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
        self.session.connection_changed.connect(self._refresh_backend_state)
        self.retranslate()
        self.refresh_actions()
        # Connected last: the editor signals while the page is still being built.
        self.editor.textChanged.connect(self._edited)
        self.editor.textChanged.connect(lambda: self.step_editor.set_source(self.source()))
        self.step_editor.source_changed.connect(self._source_from_steps)
        self._refresh_backend_state()

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
        self.step_editor.retranslate()
        self.document_tabs.setTabText(0, tr("scenarios.tab.yaml"))
        self.document_tabs.setTabText(1, tr("scenarios.tab.steps"))
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

    def _source_from_steps(self, source: str) -> None:
        if source == self.source():
            return
        self.editor.blockSignals(True)
        self.editor.setPlainText(source)
        self.editor.blockSignals(False)
        self._edited()

    def refresh_backend_library(self) -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.load_scenarios"),
            lambda token, report: client.scenarios(),
            on_success=self._show_backend_scenarios,
            banner=self.banner,
            quiet=True,
        )

    def _show_backend_scenarios(self, records: object) -> None:
        self.backend_scenarios.clear()
        for item in records if isinstance(records, list) else []:
            if isinstance(item, dict) and isinstance(item.get("scenario_id"), str):
                self.backend_scenarios.addItem(str(item["scenario_id"]))
        self.refresh_actions()

    def _refresh_backend_state(self) -> None:
        connected = self.session.connected
        self.backend_refresh.setEnabled(connected)
        self.backend_load.setEnabled(connected and self.backend_scenarios.count() > 0)
        if connected:
            self.refresh_backend_library()

    def load_from_backend(self) -> None:
        if not self.session.connected or not self.backend_scenarios.currentText():
            return
        scenario_id = self.backend_scenarios.currentText()
        client = self.session.client()
        self.context.run(
            Msg("operation.load_scenario"),
            lambda token, report: client.scenario(scenario_id),
            on_success=lambda result: self.set_source(
                str(result.get("yaml", "")), f"{scenario_id}.yml"
            ),
            on_failure=lambda error: self.banner.show_problem(self.context.problem(error)),
            banner=self.banner,
        )

    def set_source(self, source: str, name: str | None = None) -> None:
        self.document_name = name
        self.editor.setPlainText(source)
        self.step_editor.set_source(source)
        self._update_label()
        self.validate(quiet=True)

    def save_to_backend(self) -> None:
        if not self.session.connected or not self.source().strip():
            return
        scenario_id = document_id(self.source())
        if not scenario_id:
            self.banner.show_message(
                Msg("scenarios.save_backend"), Msg("scenarios.save_backend_id_required"), "warning"
            )
            return
        client = self.session.client()
        self.context.run(
            Msg("operation.save_scenario"),
            lambda token, report: client.save_scenario(scenario_id, self.source()),
            on_success=lambda result: self._backend_saved(scenario_id),
            banner=self.banner,
        )

    def _backend_saved(self, scenario_id: str) -> None:
        self.saved_source = self.source()
        self._update_label()
        self.session.log(Msg("scenarios.backend_saved", scenario=scenario_id))
        self.refresh_backend_library()

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
            action_id = str(action.get("id", ""))
            status, detail = statuses.get(action_id, ("pending", ""))
            if action_id == current and status == "pending":
                status = "running"
            rows.append(
                (
                    index,
                    status,
                    action_id,
                    action.get("kind", ""),
                    f"{action.get('source', '')} → {action.get('target', '')}",
                    action.get("service"),
                    detail,
                )
            )
        # ICMP-only sequences have no services: the column would only push the details out of
        # the narrow analysis card.
        services = any(action.get("service") for action in scenario.get("sequence") or [])
        self.sequence.setColumnHidden(SERVICE_COLUMN, not services)
        fill_table(self.sequence, rows, colors={STATUS_COLUMN: "status"})

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
                 cell_text(item.get("equals") or item.get("pattern") or item.get("minimum")
                           or item.get("maximum") or ""), "")
                for item in scenario.get("success_conditions") or []
            ] + [
                (tr("condition.role.failure_trigger"), item["action"], item["field"],
                 cell_text(item.get("equals") or item.get("pattern") or item.get("minimum")
                           or item.get("maximum") or ""), "")
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
        self.backend_load.setEnabled(
            self.session.connected and self.backend_scenarios.count() > 0 and not running
        )
        self.save_backend.setEnabled(
            self.session.connected and bool(self.source().strip()) and not running
        )
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
