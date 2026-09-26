"""Qt building blocks: task runner threading/cancellation and the telemetry model."""

import threading

from PySide6.QtCore import QThread

from polmon.client.models import TelemetryFilter, TelemetryModel
from polmon.client.tasks import Cancelled, ProgressUpdate, TaskRunner


def test_results_and_progress_arrive_on_the_gui_thread(qtbot) -> None:
    runner = TaskRunner()
    gui_thread = QThread.currentThread()
    seen: dict[str, object] = {}

    def work(token, report):
        seen["worker"] = threading.current_thread().name
        report(ProgressUpdate(1, 2, "half"))
        return 42

    def on_progress(update):
        seen["progress_on_gui"] = QThread.currentThread() is gui_thread
        seen["percent"] = update.percent

    def on_success(result):
        seen["success_on_gui"] = QThread.currentThread() is gui_thread
        seen["result"] = result

    handle = runner.submit("t", work, on_success=on_success, on_progress=on_progress)
    qtbot.waitUntil(lambda: "result" in seen, timeout=5000)
    assert seen["result"] == 42 and seen["success_on_gui"] and seen["progress_on_gui"]
    assert seen["percent"] == 50.0
    assert seen["worker"] != threading.main_thread().name
    qtbot.waitUntil(lambda: runner.in_flight == 0, timeout=5000)
    assert handle.done


def test_cancel_releases_the_ui_at_once_and_drops_late_results(qtbot) -> None:
    runner = TaskRunner()
    release = threading.Event()
    outcome: list[object] = []

    def blocking(token, report):
        release.wait(5)  # e.g. a blocking HTTP request that ignores the token
        return "late result"

    handle = runner.submit(
        "blocking", blocking, on_success=outcome.append, on_failure=outcome.append
    )
    handle.cancel()
    assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)  # immediately
    assert runner.active == [] and runner.in_flight == 1  # worker still finishing
    release.set()
    qtbot.waitUntil(lambda: runner.in_flight == 0, timeout=5000)
    assert len(outcome) == 1  # the late result was discarded


def test_task_exceptions_become_failures_not_crashes(qtbot) -> None:
    runner = TaskRunner()
    errors: list[BaseException] = []

    def broken(token, report):
        raise ValueError("bad input")

    runner.submit("broken", broken, on_success=lambda r: None, on_failure=errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=5000)
    assert isinstance(errors[0], ValueError)
    qtbot.waitUntil(lambda: runner.in_flight == 0, timeout=5000)


def test_cooperative_cancellation_interrupts_waits(qtbot) -> None:
    runner = TaskRunner()
    finished = threading.Event()

    def polling(token, report):
        try:
            token.sleep(30)
        finally:
            finished.set()

    handle = runner.submit("poll", polling)
    qtbot.wait(50)
    handle.cancel()
    assert finished.wait(2)
    qtbot.waitUntil(lambda: runner.in_flight == 0, timeout=5000)  # never outlive the pool


def events(first: int, count: int, category: str = "scenario") -> list[dict[str, object]]:
    return [
        {
            "sequence": sequence,
            "timestamp": "2026-09-26T12:00:00+00:00",
            "category": category,
            "event": f"event-{sequence}",
            "node_id": None,
            "payload": {"n": sequence},
        }
        for sequence in range(first, first + count)
    ]


def test_telemetry_model_is_append_only_bounded_and_filterable(qtbot) -> None:
    model = TelemetryModel(capacity=10)
    assert model.append(events(1, 6)) == 6
    assert model.append(events(5, 3)) == 1  # 5-6 already present; only 7 is new
    assert model.append(events(8, 6, "resource")) == 6
    assert model.rowCount() == 10 and model.dropped == 3
    assert model.events[0]["sequence"] == 4 and model.last_sequence == 13
    proxy = TelemetryFilter()
    proxy.setSourceModel(model)
    proxy.set_categories({"resource"})
    assert proxy.rowCount() == 6
    proxy.set_text("event-12")
    assert proxy.rowCount() == 1
    proxy.set_categories({"scenario", "resource"})
    proxy.set_text('"n": 5')
    assert proxy.rowCount() == 1


def test_runner_can_be_dropped_before_its_handles_are_deleted(qapp) -> None:
    """Regression: a handle's deferred deletion must not run into its runner's destruction.

    Handles used to be children of the runner and held lambdas capturing it; if the handle's
    DeferredDelete ran after the last runner reference was gone, the runner was freed from inside
    the handle's destructor and deleted it a second time (native abort on Windows CI, bus error on
    Linux when forced).
    """
    import gc
    import time

    from PySide6.QtCore import QCoreApplication, QEvent

    def scenario() -> None:
        runner = TaskRunner()
        done: list[object] = []
        runner.submit("t", lambda token, report: 1, on_success=done.append)
        deadline = time.monotonic() + 5
        while runner.in_flight and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.002)
        assert done == [1]

    for _ in range(50):
        scenario()
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_closed_runner_accepts_no_work_and_drops_late_results(qtbot) -> None:
    import threading as _threading

    runner = TaskRunner()
    release = _threading.Event()
    outcome: list[object] = []
    runner.submit(
        "slow",
        lambda token, report: release.wait(5),
        on_success=outcome.append,
        on_failure=outcome.append,
    )
    runner.close()
    assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
    late = runner.submit("late", lambda token, report: 1, on_success=outcome.append)
    assert late.done
    release.set()
    qtbot.waitUntil(lambda: runner.in_flight == 0, timeout=5000)
    assert len(outcome) == 1


def test_yaml_editor_highlights_keys_comments_and_strings(qtbot) -> None:
    from polmon.client import theme
    from polmon.client.widgets import YamlEditor

    editor = YamlEditor()
    qtbot.addWidget(editor)
    editor.setPlainText('id: lab  # comment\nnodes:\n  - id: "sensor-1"\n    count: 3\n')
    first = editor.document().firstBlock().layout().formats()
    colours = {fmt.format.foreground().color().name() for fmt in first}
    assert theme.hex_color("accent") in colours and theme.hex_color("muted") in colours
    third = editor.document().findBlockByNumber(2).layout().formats()
    assert theme.hex_color("success") in {fmt.format.foreground().color().name() for fmt in third}
    editor.setPlainText("ipv4: 10.20.0.11\ncount: 3\n")
    address = editor.document().firstBlock().layout().formats()
    assert theme.hex_color("warning") not in {f.format.foreground().color().name() for f in address}
    number = editor.document().findBlockByNumber(1).layout().formats()
    assert theme.hex_color("warning") in {f.format.foreground().color().name() for f in number}


def test_current_backend_cpu_is_derived_from_poll_deltas(qtbot, monkeypatch) -> None:
    from polmon.client.pages import dashboard
    from polmon.client.pages.dashboard import ResourceTiles

    class FakeContext:
        from polmon.client.state import Session

        session = Session()

    tiles = ResourceTiles(FakeContext())
    qtbot.addWidget(tiles)
    clock = iter([100.0, 102.0, 104.0])
    monkeypatch.setattr(dashboard.time, "monotonic", lambda: next(clock))
    assert tiles._current_cpu(10.0) is None  # first sample
    assert tiles._current_cpu(11.0) == 50.0  # 1 CPU second in 2 wall seconds
    assert tiles._current_cpu(5.0) is None  # counter went backwards: backend restarted
