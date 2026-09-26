"""Pages of the main window and the context they share."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from polmon.client.errors import Problem, describe
from polmon.client.state import Session
from polmon.client.tasks import Cancelled, ProgressUpdate, TaskHandle, TaskRunner, Work
from polmon.client.widgets import OperationProgress, ProblemBanner, page_title


class Context(QObject):
    """Services every page uses: session, task runner, operation tracking, navigation."""

    operation_changed = Signal()
    navigate_requested = Signal(str, object)
    notified = Signal(str, str)  # tone, message: a finished long operation worth attention

    def __init__(
        self,
        session: Session,
        runner: TaskRunner,
        progress: OperationProgress,
        settings: QSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.runner = runner
        self.progress = progress
        self.settings = settings
        self.operation: TaskHandle | None = None
        self.operation_name = ""
        self._operation_cancel: Callable[[], None] | None = None

    @property
    def busy(self) -> bool:
        return self.operation is not None

    def run(
        self,
        name: str,
        work: Work,
        *,
        on_success: Callable[[object], None],
        banner: ProblemBanner | None = None,
        on_failure: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[ProgressUpdate], None] | None = None,
        operation: bool = False,
        cancellable: bool = True,
        quiet: bool = False,
        on_cancel: Callable[[], None] | None = None,
    ) -> TaskHandle | None:
        """Run ``work`` off the GUI thread; failures become a banner and a log line.

        ``operation`` marks a long, state-changing action: only one runs at a time, it is shown
        in the status bar with progress and a Cancel button, and Esc cancels it. ``on_cancel``
        replaces the default cancel (stop waiting now) with a graceful one, e.g. asking the
        backend to stop; a second cancel request then abandons the operation.
        """
        if operation and self.operation is not None:
            self.session.log(
                f"{name}: another operation is running ({self.operation_name})", "warning"
            )
            return None
        session = self.session
        url, timeout = session.url, session.timeout
        if banner is not None:
            banner.clear()
        if not quiet:
            session.log(f"{name}…")

        def failed(error: BaseException) -> None:
            if isinstance(error, Cancelled):
                session.log(f"{name}: cancelled", "warning")
            else:
                problem = describe(error, url=url, timeout=timeout)
                session.log(f"{name} failed — {problem.text()}", "error")
                if banner is not None:
                    banner.show_problem(problem)
            if on_failure is not None:
                on_failure(error)

        def succeeded(result: object) -> None:
            if not quiet:
                session.log(f"{name}: done")
            on_success(result)

        handle = self.runner.submit(
            name, work, on_success=succeeded, on_failure=failed, on_progress=on_progress
        )
        if operation:
            self.operation = handle
            self.operation_name = name
            self._operation_cancel = on_cancel
            self.progress.track(handle, name, cancellable=cancellable)
            handle.finished.connect(lambda: self._operation_done(handle))
            self.operation_changed.emit()
        return handle

    def _operation_done(self, handle: TaskHandle) -> None:
        if handle is self.operation:
            self.operation = None
            self.operation_name = ""
            self._operation_cancel = None
            self.operation_changed.emit()

    def cancel_operation(self) -> bool:
        if self.operation is None:
            return False
        graceful, self._operation_cancel = self._operation_cancel, None
        if graceful is not None:
            graceful()
        else:
            self.operation.cancel()
        return True

    def notify(self, message: str, tone: str = "info") -> None:
        """Announce the end of a long operation (status bar; task-bar alert if unfocused)."""
        self.notified.emit(tone, message)

    def navigate(self, page: str, argument: object = None) -> None:
        self.navigate_requested.emit(page, argument)

    def problem(self, error: BaseException) -> Problem:
        return describe(error, url=self.session.url, timeout=self.session.timeout)

    # -- files --------------------------------------------------------------------------------

    def ask_open(self, parent: QWidget, title: str, key: str) -> Path | None:
        start = str(self.settings.value(f"folders/{key}", "") or default_folder(key))
        name, _ = QFileDialog.getOpenFileName(
            parent, title, start, "YAML documents (*.yml *.yaml);;All files (*)"
        )
        if not name:
            return None
        path = Path(name)
        self.settings.setValue(f"folders/{key}", str(path.parent))
        return path

    def ask_folder(self, parent: QWidget, title: str, key: str) -> Path | None:
        start = str(self.settings.value(f"folders/{key}", "") or default_folder(key))
        name = QFileDialog.getExistingDirectory(parent, title, start)
        if not name:
            return None
        self.settings.setValue(f"folders/{key}", name)
        return Path(name)

    def ask_save(self, parent: QWidget, title: str, suggested: str, filters: str) -> Path | None:
        start = str(Path(str(self.settings.value("folders/save", "") or Path.home())) / suggested)
        name, _ = QFileDialog.getSaveFileName(parent, title, start, filters)
        if not name:
            return None
        path = Path(name)
        self.settings.setValue("folders/save", str(path.parent))
        return path


def write_document(page: Page, path: Path, text: str, kind: str) -> bool:
    """Write ``text`` as UTF-8 with a final newline; failures go to the page banner."""
    try:
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    except OSError as error:
        page.banner.show_problem(page.context.problem(error))
        return False
    page.session.log(f"Saved {kind} to {path}")
    return True


def default_folder(key: str) -> Path:
    """``examples/<key>`` next to the working directory when present (source checkouts)."""
    candidate = Path.cwd() / "examples" / key
    return candidate if candidate.is_dir() else Path.home()


class Page(QWidget):
    key = ""
    title = ""

    def __init__(self, context: Context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.session = context.session
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(10, 8, 10, 8)
        self.root.setSpacing(6)
        self.heading = page_title(self.title)
        self.root.addWidget(self.heading)
        self.banner = ProblemBanner()
        self.root.addWidget(self.banner)
        context.operation_changed.connect(self.refresh_actions)
        self.session.connection_changed.connect(self.refresh_actions)

    def refresh_actions(self) -> None:
        """Enable exactly the actions that can succeed in the current state."""

    def activated(self, argument: object = None) -> None:
        """Called when the page becomes visible (``argument`` from ``navigate``)."""
