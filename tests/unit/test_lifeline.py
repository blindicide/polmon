import subprocess
import sys
import threading

from polmon.core import lifeline


def test_watch_process_fires_once_the_watched_process_ends() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    fired = threading.Event()
    thread = lifeline.watch_process(child.pid, fired.set, poll_seconds=0.02, grace_seconds=None)
    assert not fired.wait(0.2)
    child.kill()
    child.wait(timeout=10)
    assert fired.wait(10)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_launcher_is_watched_only_in_one_file_bundles(monkeypatch, tmp_path) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert lifeline.onefile_launcher_pid() is None

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert lifeline.onefile_launcher_pid() is None  # one-folder bundle

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123452"), raising=False)
    monkeypatch.setattr(lifeline.os, "getppid", lambda: 4242)
    assert lifeline.onefile_launcher_pid() == 4242
