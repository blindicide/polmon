"""Benchmarks: run bounded jobs with explicit limits and inspect retained raw results."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QWidget,
)

from polmon.client import theme
from polmon.client.api import ApiClientError
from polmon.client.errors import backend_message
from polmon.client.formatting import format_datetime
from polmon.client.i18n import (
    Joined,
    Msg,
    bind_fn,
    bind_text,
    bind_tip,
    has,
    status_msg,
    tr,
)
from polmon.client.pages import Context, Page
from polmon.client.reportview import benchmark_markdown
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import (
    Card,
    StateView,
    StatusBadge,
    button,
    fill_table,
    label,
    make_table,
    primary_button,
    unit_suffix,
)

KINDS = ("l0", "l1", "target")
# Plan-step fields of a running job's progress (``detail_params`` of ``detail_code: run``).
PROGRESS_FIELDS = ("endpoints", "namespaces", "l0", "l1", "repeat")
PROGRESS_CODES = ("starting", "cancelling", "other")
TERMINAL = {"succeeded", "not_run", "aborted", "failed", "cancelled"}
SCALAR_COLUMNS = 9


def progress_detail(progress: dict[str, object]) -> object:
    """The step a job is measuring, from ``detail_code``/``detail_params``; a backend without
    codes has its English ``detail`` quoted."""
    code = progress.get("detail_code")
    params = progress.get("detail_params")
    params = params if isinstance(params, dict) else {}
    if code in {"starting", "cancelling"}:
        return Msg(f"benchmarks.progress.{code}")
    if code == "run":
        known = [
            Msg(f"benchmarks.progress.field.{name}", value=params[name])
            for name in PROGRESS_FIELDS
            if name in params
        ]
        extra = [Msg.raw(f"{name}={value}") for name, value in params.items()
                 if name not in PROGRESS_FIELDS]
        return Joined([*known, *extra])
    detail = str(progress.get("detail") or "")
    return Msg("benchmarks.progress.other", detail=detail) if detail else ""

def _spin(low: int, high: int, value: int, unit: str | None = None) -> QSpinBox:
    """An integer field, with ``unit.<unit>`` after the value when given."""
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    if unit:
        unit_suffix(box, unit)
    return box


def _double(low: float, high: float, value: float, unit: str = "second") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setValue(value)
    unit_suffix(box, unit)
    return box


def _form_row(form: QFormLayout, key: str, field: QWidget, name: str) -> None:
    """A form row whose label is bound to ``key``; the field gets a stable object name and the
    label text as its accessible name."""
    field.setObjectName(name)
    caption = label(key, name="fieldLabel")
    bind_fn(field, lambda widget, key=key: widget.setAccessibleName(tr(key)), tag="accessible")
    form.addRow(caption, field)


class BenchmarksPage(Page):
    key = "benchmarks"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.job_id: str | None = None
        self.job_line: Msg | str = Msg("benchmarks.job.idle")
        self.result_document: dict[str, object] | None = None

        # Request cards side by side (workload | limits | job), results below at full width.
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE["md"])

        workload = Card("benchmarks.workload", name="workload")
        form = QFormLayout()
        form.setHorizontalSpacing(theme.SPACE["md"])
        form.setVerticalSpacing(theme.SPACE["sm"])
        self.kind = QComboBox()
        self.kind.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.kind.setMinimumContentsLength(18)
        for key in KINDS:
            self.kind.addItem("", key)
        bind_fn(
            self.kind,
            lambda combo: [
                (
                    combo.setItemText(index, tr(f"benchmark.kind_label.{combo.itemData(index)}")),
                    combo.setItemData(
                        index,
                        tr(f"benchmark.kind.{combo.itemData(index)}"),
                        Qt.ItemDataRole.ToolTipRole,
                    ),
                )
                for index in range(combo.count())
            ],
            tag="items",
        )
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.counts = QLineEdit("10 25")
        bind_tip(self.counts, "benchmarks.counts.tip")
        self.large = QCheckBox()
        self.large.setObjectName("large")
        bind_text(self.large, "benchmarks.large")
        bind_tip(self.large, "benchmarks.large.tip")
        self.namespaces = _spin(1, 16, 2)
        self.target_l0 = _spin(1, 250, 50)
        self.target_l1 = _spin(1, 8, 2)
        self.repeats = _spin(1, 10, 1)
        self.idle = _double(0, 60, 0.5)
        self.settle = _double(0, 60, 0.0)
        _form_row(form, "benchmarks.kind", self.kind, "benchmarkKind")
        _form_row(form, "benchmarks.counts", self.counts, "counts")
        form.addRow("", self.large)
        _form_row(form, "benchmarks.namespaces", self.namespaces, "namespaces")
        _form_row(form, "benchmarks.target_l0", self.target_l0, "targetL0")
        _form_row(form, "benchmarks.target_l1", self.target_l1, "targetL1")
        _form_row(form, "benchmarks.repeats", self.repeats, "repeats")
        _form_row(form, "benchmarks.idle", self.idle, "idle")
        _form_row(form, "benchmarks.settle", self.settle, "settle")
        self.form = form
        workload.body.addLayout(form)
        top.addWidget(workload, 3)

        limits = Card("benchmarks.limits", hint="benchmarks.limits.hint", name="limits")
        limits_form = QFormLayout()
        limits_form.setHorizontalSpacing(theme.SPACE["md"])
        limits_form.setVerticalSpacing(theme.SPACE["sm"])
        self.max_endpoints = _spin(1, 10_000, 50)
        self.max_namespaces = _spin(0, 1_000, 0)
        self.max_run = _double(1, 3600, 120.0)
        self.max_incremental = _spin(1, 65_536, 512, "mib")
        self.reserve = _spin(0, 1_048_576, 256, "mib")
        _form_row(limits_form, "benchmarks.max_endpoints", self.max_endpoints, "maxEndpoints")
        _form_row(limits_form, "benchmarks.max_namespaces", self.max_namespaces, "maxNamespaces")
        _form_row(limits_form, "benchmarks.max_run", self.max_run, "maxRun")
        _form_row(limits_form, "benchmarks.max_incremental", self.max_incremental,
                  "maxIncremental")
        _form_row(limits_form, "benchmarks.reserve", self.reserve, "reserve")
        limits.body.addLayout(limits_form)
        top.addWidget(limits, 3)

        job = Card("benchmarks.job", name="job")
        self.job_badge = StatusBadge()
        job.add_action(self.job_badge)
        buttons = QHBoxLayout()
        self.run_button = primary_button("benchmarks.run", tip="benchmarks.run.tip",
                                         name="runBenchmark")
        self.cancel_button = button("common.cancel", tip="benchmarks.cancel.tip",
                                    name="cancelBenchmark")
        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.context.cancel_operation)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        job.body.addLayout(buttons)
        self.job_detail = label(name="muted", wrap=True)
        self.job_detail.setObjectName("jobDetail")
        job.add(self.job_detail)
        job.body.addStretch(1)
        top.addWidget(job, 2)
        self.root.addLayout(top)

        results = Card("benchmarks.results", hint="benchmarks.results.hint", name="results")
        self.refresh_button = button("common.refresh", "quiet", tip="benchmarks.refresh.tip",
                                     name="refreshButton")
        self.refresh_button.clicked.connect(self.refresh_results)
        results.add_action(self.refresh_button)
        right = QSplitter()
        right.setChildrenCollapsible(False)
        self.results = make_table(
            (
                "column.result",
                "column.kind",
                "column.status",
                "column.started",
                "column.runs",
                "column.version",
            ),
            stretch=None,
            mono=(0, 5),
            name="benchmarkResults",
        )
        self.results.itemSelectionChanged.connect(self._result_chosen)
        self.results_state = StateView(self.results)
        right.addWidget(self.results_state)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setObjectName("benchmarkTabs")
        self.summary = QTextBrowser()
        self.summary.setObjectName("benchmarkSummary")
        self.measurements = make_table(("",), stretch=None, mono=range(SCALAR_COLUMNS),
                                       name="measurements")
        self.detail_tabs.addTab(self.summary, "")
        self.detail_tabs.addTab(self.measurements, "")
        self.detail_state = StateView(self.detail_tabs)
        right.addWidget(self.detail_state)
        right.setSizes([560, 620])
        results.add(right, 1)
        self.root.addWidget(results, 1)

        self.session.resources_changed.connect(self._adopt_backend_limits)
        self._kind_changed()
        self.retranslate()

    def retranslate(self) -> None:
        self.detail_tabs.setTabText(0, tr("benchmarks.tab.summary"))
        self.detail_tabs.setTabText(1, tr("benchmarks.tab.measurements"))
        self.job_detail.setText(str(self.job_line))
        if self.result_document is not None:
            self.summary.setMarkdown(benchmark_markdown(self.result_document))
            self._fill_measurements(self.result_document)
            self.detail_state.show_content()
        else:
            self.detail_state.show_empty(Msg("benchmarks.none_selected"),
                                         Msg("benchmarks.none_selected_hint"))
        if self.results.rowCount() == 0:
            self.results_state.show_empty(
                Msg("benchmarks.no_results") if self.session.connected else Msg("common.offline"),
                Msg("benchmarks.no_results_hint")
                if self.session.connected else Msg("common.offline_hint"),
            )

    def _set_job_line(self, line: Msg | str) -> None:
        self.job_line = line
        self.job_detail.setText(str(line))

    # -- form ---------------------------------------------------------------------------------

    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        for widget, kinds in (
            (self.counts, {"l0"}),
            (self.large, {"l0"}),
            (self.namespaces, {"l1"}),
            (self.target_l0, {"target"}),
            (self.target_l1, {"target"}),
        ):
            self.form.setRowVisible(widget, kind in kinds)
        self.max_namespaces.setValue(0 if kind == "l0" else 4)
        self.max_endpoints.setValue(50 if kind != "target" else 64)

    def _adopt_backend_limits(self) -> None:
        limits = self.session.limits()
        reserve = limits.get("memory_safety_threshold_mb")
        if isinstance(reserve, int) and self.reserve.value() < reserve:
            self.reserve.setValue(reserve)
        duration = limits.get("max_experiment_duration_seconds")
        if isinstance(duration, int | float):
            self.max_run.setMaximum(float(duration))

    def request(self) -> dict[str, object]:
        try:
            counts = [int(item) for item in self.counts.text().replace(",", " ").split()]
        except ValueError:
            counts = []
        return {
            "kind": self.kind.currentData(),
            "counts": counts or [10],
            "large": self.large.isChecked(),
            "namespaces": self.namespaces.value(),
            "l0": self.target_l0.value(),
            "l1": self.target_l1.value(),
            "repeats": self.repeats.value(),
            "idle_seconds": self.idle.value(),
            "settle_seconds": self.settle.value(),
            "limits": {
                "max_endpoints": self.max_endpoints.value(),
                "max_namespaces": self.max_namespaces.value(),
                "max_run_seconds": self.max_run.value(),
                "max_incremental_mb": self.max_incremental.value(),
                "memory_reserve_mb": self.reserve.value(),
            },
        }

    # -- jobs ---------------------------------------------------------------------------------

    def run(self) -> None:
        request = self.request()
        client = self.session.client()

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            job = client.start_benchmark(request)
            job_id = str(job["job_id"])
            report(ProgressUpdate(0, 1, Msg("benchmarks.progress.starting"), payload=job))
            failures = 0
            while str(job.get("state")) not in TERMINAL:
                token.sleep(0.5)
                try:
                    job = client.benchmark_job(job_id)
                    failures = 0
                except ApiClientError as error:
                    failures += 1
                    if error.status is not None or failures >= 12:
                        raise
                    continue
                progress = job.get("progress") or {}
                assert isinstance(progress, dict)
                report(
                    ProgressUpdate(
                        int(progress.get("completed_steps") or 0),
                        int(progress.get("total_steps") or 1),
                        progress_detail(progress),
                        float(job.get("elapsed_seconds") or 0),  # type: ignore[arg-type]
                        progress.get("eta_seconds"),  # type: ignore[arg-type]
                        job,
                    )
                )
            return job

        self.job_badge.set_status("running")
        handle = self.context.run(
            Msg("operation.benchmark", kind=tr(f"benchmark.kind.{request['kind']}")),
            work,
            on_success=self._finished,
            on_failure=lambda error: self.job_badge.set_status("error"),
            on_progress=self._progress,
            banner=self.banner,
            operation=True,
            on_cancel=self._request_cancel,
            kind="benchmark",
        )
        if handle is None:
            self.job_badge.set_status("")
        self.refresh_actions()

    def _progress(self, update: ProgressUpdate) -> None:
        job = update.payload if isinstance(update.payload, dict) else {}
        self.job_id = str(job.get("job_id") or self.job_id or "")
        self._set_job_line(
            Msg(
                "benchmarks.job.progress",
                job=self.job_id,
                state=status_msg(job.get("state")),
                completed=update.completed,
                total=update.total,
            )
        )

    def _request_cancel(self) -> None:
        job_id = self.job_id
        if not job_id:
            if self.context.operation is not None:
                self.context.operation.cancel()
            return
        client = self.session.client()
        self.job_badge.set_status("cancelling")
        self.context.run(
            Msg("operation.cancel_benchmark", job=job_id),
            lambda token, report: client.cancel_benchmark(job_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def _finished(self, job: object) -> None:
        assert isinstance(job, dict)
        state = str(job.get("state"))
        self.job_badge.set_status(state)
        message = backend_message(job.get("message_code"), job.get("message_params"),
                                  str(job.get("message") or "")) if job.get("message") else None
        parts: list[object] = [Msg("benchmarks.job.finished", job=job.get("job_id"),
                                   state=status_msg(state))]
        if message is not None:
            parts.append(message)
        if job.get("result_name"):
            parts.append(Msg("benchmarks.job.result", name=job.get("result_name")))
        self._set_job_line(Joined(parts))
        self.session.log(
            Msg("log.benchmark_finished", job=job.get("job_id"), state=status_msg(state))
        )
        self.context.notify(
            Msg("notify.benchmark", job=job.get("job_id"), state=status_msg(state)),
            "success" if state == "succeeded" else "warning",
        )
        self.refresh_results(select=str(job.get("result_name") or ""))

    # -- results ------------------------------------------------------------------------------

    def refresh_results(self, select: str = "") -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.results_state.show_loading(Msg("benchmarks.loading"))
        self.context.run(
            Msg("operation.list_benchmarks"),
            lambda token, report: client.benchmark_results(),
            on_success=lambda items: self._fill_results(items, select),  # type: ignore[arg-type]
            on_failure=lambda error: self.retranslate(),
            banner=self.banner,
            quiet=True,
        )

    def _fill_results(self, items: list[dict[str, object]], select: str) -> None:
        rows = [
            (
                item.get("name"),
                tr(f"benchmark.kind_short.{item.get('benchmark')}")
                if has(f"benchmark.kind_short.{item.get('benchmark')}")
                else item.get("benchmark"),
                item.get("status"),
                format_datetime(item.get("started_at")),
                item.get("measurement_count"),
                item.get("polmon_version"),
            )
            for item in items
        ]
        fill_table(self.results, rows, colors={2: "status"}, data=[row[0] for row in rows])
        if rows:
            self.results_state.show_content()
        else:
            self.retranslate()
        for index in range(self.results.rowCount()):
            item = self.results.item(index, 0)
            if select and item is not None and item.data(Qt.ItemDataRole.UserRole) == select:
                self.results.selectRow(index)

    def _result_chosen(self) -> None:
        rows = self.results.selectionModel().selectedRows()
        if not rows:
            return
        item = self.results.item(rows[0].row(), 0)
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        client = self.session.client()
        self.detail_state.show_loading(Msg("benchmarks.loading_result", name=name))
        self.context.run(
            Msg("operation.open_benchmark", name=name),
            lambda token, report: client.benchmark_result(name),
            on_success=self._show_result,
            banner=self.banner,
            quiet=True,
        )

    def _show_result(self, result: object) -> None:
        assert isinstance(result, dict)
        document = result.get("document") or {}
        assert isinstance(document, dict)
        self.result_document = document
        self.retranslate()

    def _fill_measurements(self, document: dict[str, object]) -> None:
        measurements = [row for row in document.get("measurements") or [] if isinstance(row, dict)]
        columns: list[str] = []
        for row in measurements:
            for key, value in row.items():
                if key not in columns and isinstance(value, int | float | str | bool):
                    columns.append(key)
        columns = columns[:SCALAR_COLUMNS]
        self.measurements.setColumnCount(max(1, len(columns)))
        # Column names are JSON keys of the result document: machine identifiers, not
        # translated; a tooltip explains the known ones.
        self.measurements.header_keys = ()  # type: ignore[attr-defined]
        self.measurements.setHorizontalHeaderLabels(columns or [tr("benchmarks.no_measurements")])
        for index, column in enumerate(columns):
            header = self.measurements.horizontalHeaderItem(index)
            if header is not None and has(f"measure.{column}"):
                header.setToolTip(tr(f"measure.{column}"))
        fill_table(self.measurements, [[row.get(key) for key in columns] for row in measurements])

    def refresh_actions(self) -> None:
        connected = self.session.connected
        running = self.context.busy and self.context.operation_kind == "benchmark"
        self.run_button.setEnabled(connected and not self.context.busy)
        self.cancel_button.setEnabled(running)
        self.refresh_button.setEnabled(connected)

    def activated(self, argument: object = None) -> None:
        if self.session.connected and self.results.rowCount() == 0:
            self.refresh_results()

