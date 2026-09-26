"""Owned backend command resolution and real process lifecycle."""

from __future__ import annotations

import os
import socket

import pytest

from polmon.client.api import ApiClient
from polmon.client.local_backend import (
    LocalBackendError,
    LocalBackendManager,
    resolve_backend_command,
)


def test_explicit_backend_override_is_resolved(tmp_path) -> None:
    executable = tmp_path / ("backend.exe" if os.name == "nt" else "backend")
    executable.write_bytes(b"test")
    assert resolve_backend_command(executable) == [str(executable.resolve())]
    with pytest.raises(LocalBackendError, match="override does not exist"):
        resolve_backend_command(tmp_path / "missing")


def test_real_local_backend_starts_runs_l0_and_stops(tmp_path) -> None:
    manager = LocalBackendManager(state_directory=tmp_path)
    connection = manager.start(timeout=15)
    process = manager.process
    assert process is not None and process.poll() is None
    assert str(connection["url"]).startswith("http://127.0.0.1:")
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    assert client.resources()["capabilities"]["fidelity"] == "l0_only"
    code = manager.stop()
    assert code is not None and process.poll() is not None
    log = manager.log_tail(10_000)
    assert manager.log_path is not None and '"POST /v1/reset HTTP/1.1" 200' in log
    if os.name == "posix":
        assert "shutdown_cleanup" in log


def test_start_retries_when_selected_port_is_taken(tmp_path, monkeypatch) -> None:
    from polmon.client import local_backend as module

    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    first = int(occupied.getsockname()[1])
    real = module._free_loopback_port
    ports = iter((first, real()))
    monkeypatch.setattr(module, "_free_loopback_port", lambda: next(ports))
    manager = LocalBackendManager(state_directory=tmp_path)
    try:
        connection = manager.start(timeout=5, attempts=2)
        assert connection["port"] != first and manager.running
    finally:
        manager.stop()
        occupied.close()


def test_local_experiment_history_survives_a_restart(tmp_path) -> None:
    from polmon.client.local_backend import _L0_SCENARIO, _L0_TOPOLOGY

    manager = LocalBackendManager(state_directory=tmp_path)
    connection = manager.start(timeout=15)
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    try:
        client.load_topology(_L0_TOPOLOGY)
        client.deploy("local-smoke")
        assert client.run_experiment("kept-1", "local-smoke", _L0_SCENARIO)["status"] == "succeeded"
    finally:
        manager.stop()

    connection = manager.start(timeout=15)
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    try:
        listed = {item["experiment_id"]: item for item in client.experiments()}
        assert listed["kept-1"]["status"] == "succeeded"
        assert client.report("kept-1")["status"] == "succeeded"
    finally:
        manager.stop()
    assert connection["data_directory"] == tmp_path / "data"
    sessions = list((tmp_path / "sessions").iterdir())
    assert len(sessions) == 2
    assert all([entry.name for entry in session.iterdir()] == ["polmon-backend.log"]
               for session in sessions)


def test_only_old_log_only_sessions_of_finished_clients_are_pruned(tmp_path) -> None:
    import subprocess
    import sys

    from polmon.client.local_backend import prune_session_logs

    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    sessions = tmp_path / "sessions"

    def session(index: int, pid: int, *, data: bool = False):
        path = sessions / f"20260101T0000{index:02d}Z-{pid}-abc123"
        path.mkdir(parents=True)
        (path / "polmon-backend.log").write_text("log", encoding="utf-8")
        if data:  # a v0.3.0 session that also held that backend's data
            (path / "var").mkdir()
            (path / "var" / "telemetry.sqlite3").write_bytes(b"results")
        return path

    old = [session(index, finished.pid) for index in range(5)]
    legacy = session(5, finished.pid, data=True)
    live = session(6, os.getppid())  # the pytest runner's parent is alive
    recent = [session(index, finished.pid) for index in range(10, 13)]

    removed = prune_session_logs(sessions, keep=3, current=recent[-1])
    assert sorted(removed) == sorted(old)
    assert legacy.is_dir() and (legacy / "var" / "telemetry.sqlite3").is_file()
    assert live.is_dir()
    assert all(path.is_dir() for path in recent)
