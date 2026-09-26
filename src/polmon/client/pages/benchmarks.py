"""Benchmarks: run bounded jobs with explicit limits and inspect retained raw results."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from polmon.client.api import ApiClientError
from polmon.client.formatting import format_datetime
from polmon.client.pages import Context, Page
from polmon.client.tasks import CancelToken, ProgressUpdate
from polmon.client.widgets import StatusBadge, fill_table, make_table, muted, primary_button

KINDS = (
    ("l0", "L0 synthetic endpoints (rootless)"),
    ("l1", "L1 Linux namespaces (privileged lab)"),
    ("target", "Phase I target: L0 + L1 (privileged lab)"),
)
TERMINAL = {"succeeded", "not_run", "aborted", "failed", "cancelled"}
SCALAR_COLUMNS = 9


def _spin(low: int, high: int, value: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


def _double(low: float, high: float, value: float, suffix: str = " s") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class BenchmarksPage(Page):
    key = "benchmarks"
    title = "Benchmarks"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.job_id: str | None = None

        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        workload = QGroupBox("Workload")
        form = QFormLayout(workload)
        self.kind = QComboBox()
        for key, label in KINDS:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.counts = QLineEdit("10 25")
        self.counts.setToolTip("Space-separated L0 endpoint counts; above 50 requires Large")
        self.large = QCheckBox("Large (explicit opt-in for counts above 50)")
        self.namespaces = _spin(1, 16, 2)
        self.target_l0 = _spin(1, 250, 50)
        self.target_l1 = _spin(1, 8, 2)
        self.repeats = _spin(1, 10, 1)
        self.idle = _double(0, 60, 0.5)
        self.settle = _double(0, 60, 0.0)
        form.addRow("Kind", self.kind)
        form.addRow("L0 counts", self.counts)
        form.addRow("", self.large)
        form.addRow("Namespaces", self.namespaces)
        form.addRow("Target L0", self.target_l0)
        form.addRow("Target L1", self.target_l1)
        form.addRow("Repeats", self.repeats)
        form.addRow("Idle per run", self.idle)
        form.addRow("Settle between runs", self.settle)
        self.form = form
        left_layout.addWidget(workload)

        limits = QGroupBox("Explicit limits (checked against the backend's own limits)")
        limits_form = QFormLayout(limits)
        self.max_endpoints = _spin(1, 10_000, 50)
        self.max_namespaces = _spin(0, 1_000, 0)
        self.max_run = _double(1, 3600, 120.0)
        self.max_incremental = _spin(1, 65_536, 512, " MiB")
        self.reserve = _spin(0, 1_048_576, 256, " MiB")
        limits_form.addRow("Max endpoints", self.max_endpoints)
        limits_form.addRow("Max namespaces", self.max_namespaces)
        limits_form.addRow("Max seconds per run", self.max_run)
        limits_form.addRow("Max incremental memory", self.max_incremental)
        limits_form.addRow("Memory reserve", self.reserve)
        left_layout.addWidget(limits)

        run_box = QGroupBox("Job")
        run_layout = QVBoxLayout(run_box)
        buttons = QHBoxLayout()
        self.run_button = primary_button("Run benchmark")
        self.cancel_button = QPushButton("Cancel")
        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.context.cancel_operation)
        self.job_badge = StatusBadge()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self.job_badge)
        run_layout.addLayout(buttons)
        self.job_detail = muted("Benchmarks run on the backend host, one fresh process per run.")
        run_layout.addWidget(self.job_detail)
        left_layout.addWidget(run_box)
        left_layout.addStretch(1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(muted("Retained results on the backend"), 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_results)
        row.addWidget(self.refresh_button)
        right_layout.addLayout(row)
        self.results = make_table(
            ("Result", "Kind", "Status", "Started", "Runs", "polmon"), stretch=0
        )
        self.results.itemSelectionChanged.connect(self._result_chosen)
        right_layout.addWidget(self.results, 1)
        self.detail_tabs = QTabWidget()
        self.summary = QTextBrowser()
        self.measurements = make_table(("",), stretch=None)
        self.detail_tabs.addTab(self.summary, "Summary")
        self.detail_tabs.addTab(self.measurements, "Measurements")
        right_layout.addWidget(self.detail_tabs, 2)
        splitter.addWidget(right)
        splitter.setSizes([420, 700])
        self.root.addWidget(splitter, 1)

        self.session.resources_changed.connect(self._adopt_backend_limits)
        self._kind_changed()

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
            report(ProgressUpdate(0, 1, "starting", payload=job))
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
                        str(progress.get("detail") or ""),
                        float(job.get("elapsed_seconds") or 0),  # type: ignore[arg-type]
                        progress.get("eta_seconds"),  # type: ignore[arg-type]
                        job,
                    )
                )
            return job

        self.job_badge.set_status("running")
        handle = self.context.run(
            f"Benchmark {request['kind']}",
            work,
            on_success=self._finished,
            on_failure=lambda error: self.job_badge.set_status("error"),
            on_progress=self._progress,
            banner=self.banner,
            operation=True,
            on_cancel=self._request_cancel,
        )
        if handle is None:
            self.job_badge.set_status("")
        self.refresh_actions()

    def _progress(self, update: ProgressUpdate) -> None:
        job = update.payload if isinstance(update.payload, dict) else {}
        self.job_id = str(job.get("job_id") or self.job_id or "")
        self.job_detail.setText(
            f"Job {self.job_id}: {job.get('state')} · step {update.completed}/{update.total} · "
            f"{update.detail}"
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
            f"Cancel benchmark {job_id}",
            lambda token, report: client.cancel_benchmark(job_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def _finished(self, job: object) -> None:
        assert isinstance(job, dict)
        state = str(job.get("state"))
        self.job_badge.set_status(state)
        message = job.get("message") or ""
        self.job_detail.setText(
            f"Job {job.get('job_id')}: {state}"
            + (f" — {message}" if message else "")
            + (f" · result {job.get('result_name')}" if job.get("result_name") else "")
        )
        self.session.log(f"Benchmark job {job.get('job_id')} finished: {state} {message}".strip())
        self.refresh_results(select=str(job.get("result_name") or ""))

    # -- results ------------------------------------------------------------------------------

    def refresh_results(self, select: str = "") -> None:
        if not self.session.connected:
            return
        client = self.session.client()
        self.context.run(
            "List benchmark results",
            lambda token, report: client.benchmark_results(),
            on_success=lambda items: self._fill_results(items, select),  # type: ignore[arg-type]
            banner=self.banner,
            quiet=True,
        )

    def _fill_results(self, items: list[dict[str, object]], select: str) -> None:
        rows = [
            (
                item.get("name"),
                item.get("benchmark"),
                item.get("status"),
                format_datetime(item.get("started_at")),
                item.get("measurement_count"),
                item.get("polmon_version"),
            )
            for item in items
        ]
        fill_table(self.results, rows, colors={2: "status"})
        for index, row in enumerate(rows):
            if select and row[0] == select:
                self.results.selectRow(index)

    def _result_chosen(self) -> None:
        rows = self.results.selectionModel().selectedRows()
        if not rows:
            return
        item = self.results.item(rows[0].row(), 0)
        if item is None:
            return
        name = item.text()
        client = self.session.client()
        self.context.run(
            f"Open benchmark result {name}",
            lambda token, report: client.benchmark_result(name),
            on_success=self._show_result,
            banner=self.banner,
            quiet=True,
        )

    def _show_result(self, result: object) -> None:
        assert isinstance(result, dict)
        summary = result.get("summary_markdown")
        document = result.get("document") or {}
        assert isinstance(document, dict)
        error = document.get("error")
        text = summary or "No summary available."
        if isinstance(error, dict) and error.get("message"):
            text = f"**{error['message']}**\n\n{text}"
        self.summary.setMarkdown(str(text))
        measurements = [row for row in document.get("measurements") or [] if isinstance(row, dict)]
        columns: list[str] = []
        for row in measurements:
            for key, value in row.items():
                if key not in columns and isinstance(value, int | float | str | bool):
                    columns.append(key)
        columns = columns[:SCALAR_COLUMNS]
        self.measurements.setColumnCount(max(1, len(columns)))
        self.measurements.setHorizontalHeaderLabels(columns or ["No measurements"])
        fill_table(self.measurements, [[row.get(key) for key in columns] for row in measurements])

    def refresh_actions(self) -> None:
        connected = self.session.connected
        running = self.context.busy and self.context.operation_name.startswith("Benchmark")
        self.run_button.setEnabled(connected and not self.context.busy)
        self.cancel_button.setEnabled(running)
        self.refresh_button.setEnabled(connected)

    def activated(self, argument: object = None) -> None:
        if self.session.connected and self.results.rowCount() == 0:
            self.refresh_results()
