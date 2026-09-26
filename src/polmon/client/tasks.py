"""Off-GUI-thread work with cancellation; results always arrive on the GUI thread.

Each task runs a plain function on a bounded :class:`QThreadPool`. The function receives a
:class:`CancelToken` and a ``report`` callable for progress. Outcomes travel back through
signals of a :class:`TaskHandle`, a ``QObject`` created on (and therefore living in) the GUI
thread, so the callbacks connected to it always execute on the GUI thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot


class Cancelled(Exception):  # noqa: N818 - control-flow signal, not an error condition
    """Raised inside a task when its token was cancelled."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled

    def sleep(self, seconds: float) -> None:
        """Wait up to ``seconds``; return early and raise :class:`Cancelled` on cancel."""
        if self._event.wait(seconds):
            raise Cancelled


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    completed: int
    total: int
    detail: str = ""
    elapsed: float | None = None
    eta: float | None = None
    payload: object = None

    @property
    def percent(self) -> float | None:
        return 100.0 * self.completed / self.total if self.total else None


Report = Callable[[ProgressUpdate], None]
Work = Callable[[CancelToken, Report], object]


class TaskHandle(QObject):
    """GUI-thread endpoint of one task; user callbacks run only from these slots.

    ``finished`` fires once for the UI: on the worker's outcome, or immediately on cancel.
    ``released`` fires when the worker has really returned, after which the handle may be
    deleted (a cancelled task may still be completing a blocking call, or rolling back).
    """

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()
    released = Signal()
    _worker_progress = Signal(object)
    _worker_done = Signal(object, object)  # (result, error)

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.token = CancelToken()
        self.started = time.monotonic()
        self.done = False
        self.worker_finished = False
        self.cancel_requested = False
        self.last_progress: ProgressUpdate | None = None
        self._worker_progress.connect(self._on_progress)
        self._worker_done.connect(self._on_done)

    def cancel(self) -> None:
        """Stop waiting now: the UI is released at once and any later result is discarded."""
        if self.done:
            return
        self.cancel_requested = True
        self.token.cancel()
        self.done = True
        self.failed.emit(Cancelled())
        self.finished.emit()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @Slot(object)
    def _on_progress(self, update: ProgressUpdate) -> None:
        if not self.done:
            self.last_progress = update
            self.progress.emit(update)

    @Slot(object, object)
    def _on_done(self, result: object, error: object) -> None:
        self.worker_finished = True
        if not self.done:
            self.done = True
            if error is not None:
                self.failed.emit(error)
            else:
                self.succeeded.emit(result)
            self.finished.emit()
        self.released.emit()


def _execute(handle: TaskHandle, work: Work) -> None:
    """Worker-thread body of one task; outcomes are emitted, never raised."""

    def report(update: ProgressUpdate) -> None:
        if not handle.token.cancelled:
            handle._worker_progress.emit(update)

    try:
        result = work(handle.token, report)
    except BaseException as error:  # noqa: BLE001 - delivered to the GUI, never swallowed
        handle._worker_done.emit(None, error)
    else:
        handle._worker_done.emit(result, None)


class TaskRunner(QObject):
    """Owns the pool and keeps every in-flight handle alive until it has finished."""

    task_started = Signal(object)
    task_finished = Signal(object)

    def __init__(self, parent: QObject | None = None, *, max_threads: int = 4) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        # Strong references to each handle and its worker callable until the worker has
        # returned: nothing a running worker touches can be collected or deleted under it.
        self._active: dict[TaskHandle, Callable[[], None]] = {}

    def submit(
        self,
        name: str,
        work: Work,
        *,
        on_success: Callable[[object], None] | None = None,
        on_failure: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[ProgressUpdate], None] | None = None,
    ) -> TaskHandle:
        handle = TaskHandle(name, self)
        if on_success is not None:
            handle.succeeded.connect(on_success)
        if on_failure is not None:
            handle.failed.connect(on_failure)
        if on_progress is not None:
            handle.progress.connect(on_progress)
        handle.finished.connect(lambda: self.task_finished.emit(handle))
        handle.released.connect(lambda: self._released(handle))

        def run() -> None:
            _execute(handle, work)

        self._active[handle] = run
        self.task_started.emit(handle)
        self.pool.start(run)
        return handle

    def _released(self, handle: TaskHandle) -> None:
        self._active.pop(handle, None)
        handle.deleteLater()

    @property
    def active(self) -> list[TaskHandle]:
        return [handle for handle in self._active if not handle.done]

    @property
    def in_flight(self) -> int:
        """Workers still running, including cancelled ones finishing a blocking call."""
        return len(self._active)

    def cancel_all(self) -> None:
        for handle in list(self._active):
            handle.cancel()

    def wait(self, milliseconds: int) -> bool:
        """Block up to ``milliseconds`` for running work (shutdown only)."""
        return self.pool.waitForDone(milliseconds)
