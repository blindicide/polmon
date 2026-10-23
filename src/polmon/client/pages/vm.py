"""Виртуальные машины L1: образ гостя, готовность хоста и пробный запуск двух гостей на KVM."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from polmon.client import theme
from polmon.client.api import ApiClientError
from polmon.client.errors import backend_message
from polmon.client.formatting import (
    duration,
    format_bytes,
    format_datetime,
    format_duration,
    mebibytes,
    size,
)
from polmon.client.i18n import Joined, Msg, bind_fn, status_msg, tr
from polmon.client.pages import Context, Page
from polmon.client.tasks import Cancelled, CancelToken, ProgressUpdate
from polmon.client.widgets import (
    Card,
    StateView,
    StatusBadge,
    button,
    fill_table,
    label,
    make_table,
    primary_button,
)

MODES = ("userns", "netns")
ACTIONS = ("acquire", "verify", "run")
TERMINAL = {"succeeded", "failed", "cancelled"}
POLL_SECONDS = 1.0
LOST_POLLS = 12
EMPTY = "—"


def _guest_rows(job: dict[str, object] | None) -> list[list[object]]:
    """Строки таблицы гостей из результата удачного запуска: проба, ЦП, память, диск, трафик."""
    result = job.get("result") if isinstance(job, dict) else None
    if not isinstance(result, dict):
        return []
    sample = result.get("sample")
    nodes = sample.get("nodes") if isinstance(sample, dict) else None
    probes = result.get("probes")
    rows: list[list[object]] = []
    for node_id, entry in (nodes if isinstance(nodes, dict) else {}).items():
        entry = entry if isinstance(entry, dict) else {}
        checks = probes.get(node_id) if isinstance(probes, dict) else None
        if isinstance(checks, list) and checks:
            probe = "ok" if all(item is True for item in checks) else "failed"
        else:
            probe = "unknown"
        counters = [
            value for value in (entry.get("interfaces") or {}).values() if isinstance(value, dict)
        ]
        received = sum(int(item.get("rx_bytes") or 0) for item in counters) if counters else None
        sent = sum(int(item.get("tx_bytes") or 0) for item in counters) if counters else None
        rows.append(
            [
                node_id,
                probe,
                format_duration(entry.get("cpu_seconds")),
                format_bytes(entry.get("rss_bytes")),
                format_bytes(entry.get("overlay_allocated_bytes")),
                format_bytes(received),
                format_bytes(sent),
            ]
        )
    return rows


class VMPage(Page):
    key = "vm"

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.job_id: str | None = None
        self.job_line: Msg | str = Msg("vm.job.idle")
        # Последний ответ бэкенда: status, readiness и jobs; None, пока он не получен.
        self.snapshot: dict[str, object] | None = None

        # Ряд карточек (готовность | образ | лаборатория), под ним результаты на всю ширину.
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE["sm"] + 2)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE["md"])

        host = Card("vm.host", hint="vm.host.hint", name="vmHost")
        self.host_badge = StatusBadge()
        host.add_action(self.host_badge)
        self.refresh_button = button(
            "common.refresh", "quiet", tip="vm.refresh.tip", name="refreshVM"
        )
        self.refresh_button.clicked.connect(self.refresh)
        host.add_action(self.refresh_button)
        self.host_detail = label(name="muted", wrap=True)
        self.host_detail.setObjectName("vmHostDetail")
        host.add(self.host_detail)
        host.body.addStretch(1)
        top.addWidget(host, 3)

        image = Card("vm.image", hint="vm.image.hint", name="vmImage")
        self.image_detail = label(name="muted", wrap=True)
        self.image_detail.setObjectName("vmImageDetail")
        self.image_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        image.add(self.image_detail)
        image.body.addStretch(1)
        top.addWidget(image, 4)

        lab = Card("vm.lab", hint="vm.lab.hint", name="vmLab")
        self.job_badge = StatusBadge()
        lab.add_action(self.job_badge)
        self.mode = QComboBox()
        self.mode.setObjectName("vmMode")
        self.mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.mode.setMinimumContentsLength(22)
        for key in MODES:
            self.mode.addItem("", key)
        bind_fn(
            self.mode,
            lambda combo: [
                (
                    combo.setItemText(index, tr(f"vm.mode.{combo.itemData(index)}")),
                    combo.setItemData(
                        index,
                        tr(f"vm.mode.{combo.itemData(index)}.tip"),
                        Qt.ItemDataRole.ToolTipRole,
                    ),
                )
                for index in range(combo.count())
            ],
            tag="items",
        )
        bind_fn(self.mode, lambda combo: combo.setAccessibleName(tr("vm.mode")), tag="accessible")
        self.mode.currentIndexChanged.connect(lambda _=0: self.refresh_actions())
        mode_row = QHBoxLayout()
        mode_row.addWidget(label("vm.mode", name="fieldLabel"))
        mode_row.addWidget(self.mode, 1)
        lab.body.addLayout(mode_row)
        lab_buttons = QHBoxLayout()
        self.run_button = primary_button("vm.run", tip="vm.run.tip", name="runVM")
        self.cancel_button = button("common.cancel", tip="vm.cancel.tip", name="cancelVM")
        self.recover_button = button("vm.recover", "quiet", tip="vm.recover.tip", name="recoverVM")
        self.run_button.clicked.connect(lambda: self.start("run"))
        self.cancel_button.clicked.connect(self.context.cancel_operation)
        self.recover_button.clicked.connect(self.recover)
        lab_buttons.addWidget(self.run_button)
        lab_buttons.addWidget(self.cancel_button)
        lab_buttons.addWidget(self.recover_button)
        lab_buttons.addStretch(1)
        lab.body.addLayout(lab_buttons)
        self.job_detail = label(name="muted", wrap=True)
        self.job_detail.setObjectName("vmJobDetail")
        lab.add(self.job_detail)
        lab.body.addStretch(1)
        top.addWidget(lab, 3)

        column.addLayout(top)

        results = Card("vm.results", hint="vm.results.hint", name="vmResults")
        self.summary = label(name="muted", wrap=True)
        self.summary.setObjectName("vmSummary")
        results.add(self.summary)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        self.guests = make_table(
            (
                "column.node",
                "vm.column.probe",
                "vm.column.cpu",
                "vm.column.rss",
                "vm.column.overlay",
                "vm.column.rx",
                "vm.column.tx",
            ),
            stretch=None,
            mono=(0,),
            name="vmGuests",
        )
        self.jobs = make_table(
            (
                "vm.column.job",
                "column.action",
                "vm.column.mode",
                "column.status",
                "column.started",
                "vm.column.elapsed",
            ),
            stretch=None,
            mono=(0,),
            name="vmJobs",
        )
        self.guests_state = StateView(self.guests)
        self.jobs_state = StateView(self.jobs)
        split.addWidget(self.guests_state)
        split.addWidget(self.jobs_state)
        split.setSizes([620, 520])
        results.add(split, 1)
        column.addWidget(results, 1)

        self.view = StateView(content)
        self.root.addWidget(self.view, 1)
        self.session.connection_changed.connect(self._connection_changed)
        self.session.resources_changed.connect(self.retranslate)
        self.retranslate()
        self.refresh_actions()

    # -- состояние ----------------------------------------------------------------------------

    def _section(self, name: str) -> dict[str, object]:
        value = (self.snapshot or {}).get(name)
        return value if isinstance(value, dict) else {}

    @property
    def advertised(self) -> bool:
        return bool(self.session.capabilities.get("vm"))

    @property
    def usable(self) -> bool:
        """Дополнение есть и сервер не работает от root: задания принимаются."""
        status = self._section("status")
        return bool(status.get("available")) and not status.get("as_root")

    def _mode_ready(self, mode: object) -> bool:
        modes = self._section("readiness").get("modes")
        return isinstance(modes, dict) and bool(modes.get(str(mode)))

    def _image_present(self) -> bool:
        image = self._section("status").get("image")
        return isinstance(image, dict) and bool(image.get("present"))

    def _running_job(self) -> str | None:
        running = self._section("status").get("running")
        return str(running) if running else None

    def _connection_changed(self) -> None:
        if not self.session.connected:
            self.snapshot = None
            self.job_id = None
            self.job_badge.set_status("")
            self.job_line = Msg("vm.job.idle")
        self.retranslate()
        self.refresh_actions()

    # -- отображение --------------------------------------------------------------------------

    def retranslate(self) -> None:
        self.job_detail.setText(str(self.job_line))
        if not self.session.connected:
            self.view.show_empty(Msg("common.offline"), Msg("common.offline_hint"))
            return
        if not self.advertised:
            self.view.show_empty(Msg("vm.unavailable"), Msg("vm.unavailable_hint"))
            return
        if self.snapshot is None:
            self.view.show_loading(Msg("vm.loading"))
            return
        self.view.show_content()
        self._render_host()
        self._render_image()
        self._render_modes()
        self._render_results()

    def _render_host(self) -> None:
        readiness = self._section("readiness")
        self.host_badge.set_status("ok" if readiness.get("ready") else "failed")
        lines: list[object] = [
            Msg(
                f"vm.host.mode.{mode}",
                state=Msg("vm.state.available" if self._mode_ready(mode) else "vm.state.missing"),
            )
            for mode in MODES
        ]
        missing = [
            backend_message(code, None, str(code))
            for code in readiness.get("missing") or []
            if isinstance(code, str)
        ]
        if missing:
            lines.append(Msg("vm.host.missing", items=Joined(missing)))
        if readiness.get("version"):
            lines.append(Msg("vm.host.version", version=str(readiness["version"])))
        self.host_detail.setText("\n".join(str(line) for line in lines))

    def _render_image(self) -> None:
        image = self._section("status").get("image")
        image = image if isinstance(image, dict) else {}
        message = (
            Msg("vm.image.present", size=size(image.get("size_bytes")))
            if image.get("present")
            else Msg("vm.image.absent")
        )
        self.image_detail.setText(str(message))

    def _render_modes(self) -> None:
        """Режим через sudo выбирается, только если готовность хоста его подтвердила."""
        model = self.mode.model()
        for index in range(self.mode.count()):
            item = model.item(index)  # type: ignore[attr-defined]
            if item is not None:
                item.setEnabled(self._mode_ready(self.mode.itemData(index)) or index == 0)
        item = model.item(self.mode.currentIndex())  # type: ignore[attr-defined]
        if item is not None and not item.isEnabled():
            self.mode.setCurrentIndex(0)

    def _render_results(self) -> None:
        jobs = [job for job in self.snapshot.get("jobs") or [] if isinstance(job, dict)]  # type: ignore[union-attr]
        rows = [
            (
                job.get("job_id"),
                tr(f"vm.action.{job.get('action')}"),
                tr(f"vm.mode.short.{job.get('mode')}"),
                job.get("state"),
                format_datetime(job.get("started_at")),
                format_duration(job.get("elapsed_seconds")),
            )
            for job in jobs
        ]
        fill_table(self.jobs, rows, colors={3: "status"}, data=[row[0] for row in rows])
        if rows:
            self.jobs_state.show_content()
        else:
            self.jobs_state.show_empty(Msg("vm.no_jobs"), Msg("vm.no_jobs_hint"))
        last = next(
            (job for job in jobs if job.get("action") == "run" and job.get("state") == "succeeded"),
            None,
        )
        guests = _guest_rows(last)
        fill_table(self.guests, guests, colors={1: "status"})
        if guests and last is not None:
            self.guests_state.show_content()
            result = last["result"]
            sample = result.get("sample") if isinstance(result, dict) else None  # type: ignore[index]
            sample = sample if isinstance(sample, dict) else {}
            self.summary.setText(
                str(
                    Msg(
                        "vm.summary",
                        job=Msg.raw(str(last.get("job_id"))),
                        ready=duration(result.get("ready_seconds")),  # type: ignore[union-attr]
                        uptime=duration(sample.get("uptime_seconds")),
                        memory=mebibytes(sample.get("guest_memory_mb_each")),
                    )
                )
            )
        else:
            self.guests_state.show_empty(Msg("vm.no_run"), Msg("vm.no_run_hint"))
            self.summary.setText(str(Msg("vm.summary.none")))

    # -- обновление и задания -----------------------------------------------------------------

    def refresh(self) -> None:
        if not self.session.connected or not self.advertised:
            return
        client = self.session.client()

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            return {
                "status": client.vm_status(),
                "readiness": client.vm_readiness(),
                "jobs": client.vm_jobs(),
            }

        self.context.run(
            Msg("operation.vm_refresh"),
            work,
            on_success=self._adopt,
            on_failure=lambda error: self.retranslate(),
            banner=self.banner,
            quiet=True,
        )

    def _adopt(self, snapshot: object) -> None:
        assert isinstance(snapshot, dict)
        self.snapshot = snapshot
        running = self._running_job()
        if running and self.job_id is None:
            self.job_id = running
        self.retranslate()
        self.refresh_actions()

    def start(self, action: str) -> None:
        request: dict[str, object] = {"action": action, "mode": str(self.mode.currentData())}
        client = self.session.client()

        def work(token: CancelToken, report) -> dict[str, object]:  # noqa: ANN001
            job = client.start_vm_job(request)
            job_id = str(job["job_id"])
            report(ProgressUpdate(0, 0, Msg("vm.progress.starting"), payload=job))
            failures = 0
            while str(job.get("state")) not in TERMINAL:
                try:
                    token.sleep(POLL_SECONDS)
                except Cancelled:
                    # Отмена пришла до первого ответа с номером задания: останавливаем его здесь.
                    with contextlib.suppress(ApiClientError):
                        client.cancel_vm_job(job_id)
                    raise
                try:
                    job = client.vm_job(job_id)
                    failures = 0
                except ApiClientError as error:
                    failures += 1
                    if error.status is not None or failures >= LOST_POLLS:
                        raise
                    continue
                report(
                    ProgressUpdate(
                        0,
                        0,
                        Msg(f"vm.action.{action}"),
                        float(job.get("elapsed_seconds") or 0),  # type: ignore[arg-type]
                        None,
                        job,
                    )
                )
            return job

        self.job_badge.set_status("running")
        handle = self.context.run(
            Msg("operation.vm", action=Msg(f"vm.action.{action}")),
            work,
            on_success=self._finished,
            on_failure=self._failed,
            on_progress=self._progress,
            banner=self.banner,
            operation=True,
            on_cancel=self._request_cancel,
            kind="vm",
        )
        if handle is None:
            self.job_badge.set_status("")
        self.refresh_actions()

    def _failed(self, error: BaseException) -> None:
        self.job_id = None
        self.job_badge.set_status("cancelled" if isinstance(error, Cancelled) else "error")
        self.refresh()

    def _progress(self, update: ProgressUpdate) -> None:
        job = update.payload if isinstance(update.payload, dict) else {}
        self.job_id = str(job.get("job_id") or self.job_id or "")
        self.job_line = Msg(
            "vm.job.progress",
            job=Msg.raw(self.job_id),
            state=status_msg(job.get("state")),
            action=Msg(f"vm.action.{job.get('action')}"),
            elapsed=duration(job.get("elapsed_seconds")),
        )
        self.job_detail.setText(str(self.job_line))

    def _request_cancel(self) -> None:
        job_id = self.job_id
        if not job_id:
            if self.context.operation is not None:
                self.context.operation.cancel()
            return
        client = self.session.client()
        self.job_badge.set_status("cancelling")
        self.context.run(
            Msg("operation.vm_cancel", job=Msg.raw(job_id)),
            lambda token, report: client.cancel_vm_job(job_id),
            on_success=lambda result: None,
            banner=self.banner,
        )

    def _finished(self, job: object) -> None:
        assert isinstance(job, dict)
        state = str(job.get("state"))
        self.job_id = None
        self.job_badge.set_status(state)
        parts: list[object] = [
            Msg("vm.job.finished", job=Msg.raw(str(job.get("job_id"))), state=status_msg(state))
        ]
        if job.get("message_code") or job.get("message"):
            parts.append(
                backend_message(
                    job.get("message_code"),
                    job.get("message_params"),
                    str(job.get("message") or ""),
                )
            )
        self.job_line = Joined(parts)
        self.job_detail.setText(str(self.job_line))
        self.session.log(
            Msg("log.vm_finished", job=Msg.raw(str(job.get("job_id"))), state=status_msg(state))
        )
        self.context.notify(
            Msg("notify.vm", job=Msg.raw(str(job.get("job_id"))), state=status_msg(state)),
            "success" if state == "succeeded" else "warning",
        )
        self.refresh()

    def recover(self) -> None:
        client = self.session.client()
        self.context.run(
            Msg("operation.vm_recover"),
            lambda token, report: client.recover_vm(),
            on_success=self._recovered,
            banner=self.banner,
        )

    def _recovered(self, result: object) -> None:
        values = result if isinstance(result, dict) else {}
        self.session.log(
            Msg(
                "log.vm_recovered",
                directories=values.get("directories", 0),
                recovered=values.get("recovered", 0),
                failed=values.get("failed", 0),
            )
        )
        self.context.notify(Msg("notify.vm_recovered"), "success")
        self.refresh()

    # -- доступность действий -----------------------------------------------------------------

    def refresh_actions(self) -> None:
        connected = self.session.connected and self.advertised
        idle = connected and not self.context.busy and self._running_job() is None
        running = self.context.busy and self.context.operation_kind == "vm"
        usable = self.usable
        present = self._image_present()
        self.refresh_button.setEnabled(connected)
        self.run_button.setEnabled(
            idle and usable and present and self._mode_ready(self.mode.currentData())
        )
        self.recover_button.setEnabled(idle and bool(self._section("status").get("available")))
        self.cancel_button.setEnabled(running)

    def activated(self, argument: object = None) -> None:
        if self.session.connected and self.advertised:
            self.refresh()
