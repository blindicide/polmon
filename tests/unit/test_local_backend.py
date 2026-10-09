"""Owned backend command resolution and real process lifecycle."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

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
    assert code == 0 and process.poll() is not None  # graceful via the stdin lifeline
    log = manager.log_tail(10_000)
    assert manager.log_path is not None and '"POST /v1/reset HTTP/1.1" 200' in log
    assert '"event":"owner_exit"' in log and "shutdown_cleanup" in log


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


def test_packaged_self_test_is_repeatable_and_leaves_operator_state_alone(
    tmp_path, monkeypatch
) -> None:
    from polmon.client import local_backend as module

    monkeypatch.setattr(module, "default_state_directory", lambda: tmp_path / "operator")
    for _ in range(2):  # a fixed experiment id must not collide with persisted history
        record = module.packaged_workflow_self_test()
        assert record["experiment_status"] == "succeeded"
    assert not (tmp_path / "operator").exists()


def test_backend_leaves_when_its_client_dies_abruptly(tmp_path) -> None:
    import json
    import subprocess
    import sys
    import time

    from polmon.client.local_backend import _pid_alive

    output = tmp_path / "crash.json"
    probe = (
        "from pathlib import Path; from polmon.client.local_backend import crash_cleanup_probe; "
        f"crash_cleanup_probe(Path({str(output)!r}), state_directory=Path({str(tmp_path)!r}))"
    )
    # crash_cleanup_probe ends with os._exit(77): no cleanup code runs in the client.
    assert subprocess.run([sys.executable, "-c", probe], timeout=60).returncode == 77
    record = json.loads(output.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 20
    while _pid_alive(int(record["pid"])) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_alive(int(record["pid"])), "the backend outlived its crashed client"
    log = Path(record["log_path"]).read_text(encoding="utf-8")
    assert '"event":"owner_exit"' in log or os.name == "nt"  # Windows: the job may kill first


def test_frozen_client_embeds_the_l0_backend_in_its_own_executable(tmp_path, monkeypatch) -> None:
    # The frozen client ships no separate backend executable, service, or sibling bundle on either
    # platform: it re-invokes its own executable with BACKEND_MODE_FLAG, which app.main dispatches
    # to backend.main. No sibling layout is consulted, so none can shadow the embedded backend.
    from polmon.client.local_backend import BACKEND_MODE_FLAG

    client = tmp_path / "polmon-dist" / ("polmon-client.exe" if os.name == "nt" else
                                          "polmon-client")
    client.parent.mkdir()
    client.write_bytes(b"client")
    monkeypatch.setattr(sys, "executable", str(client))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("POLMON_BACKEND_EXECUTABLE", raising=False)
    # A stale sibling backend must NOT be used even if one is present next to the client.
    sibling = client.parent / ("polmon-backend.exe" if os.name == "nt" else "polmon-backend")
    sibling.write_bytes(b"stale sibling")
    monkeypatch.setattr("shutil.which", lambda name: str(sibling))

    assert resolve_backend_command() == [str(client.resolve()), BACKEND_MODE_FLAG]


def test_embedded_backend_dispatch_opens_sqlite_and_runs_l0(tmp_path, monkeypatch) -> None:
    # Regression for polmon 0.4.1 `ModuleNotFoundError: No module named '_sqlite3'`: drive the
    # manager through the embedded self-dispatch path (app.main --polmon-run-embedded-backend ->
    # backend.main) rather than the bare `-m polmon.backend` fallback, and run a real L0 workflow.
    # The experiment persists to the backend's SQLite telemetry store, so a clean success proves
    # the embedded dispatch loads and uses sqlite3/_sqlite3 with no import error. `-m` on the
    # client package runs app.py as __main__, exactly the frozen executable's dispatch code.
    from polmon.client import local_backend as module
    from polmon.client.local_backend import _L0_SCENARIO, _L0_TOPOLOGY, BACKEND_MODE_FLAG

    embedded = [sys.executable, "-m", "polmon.client.app", BACKEND_MODE_FLAG]
    monkeypatch.setattr(module, "resolve_backend_command", lambda override=None: list(embedded))

    manager = LocalBackendManager(state_directory=tmp_path)
    connection = manager.start(timeout=15)
    assert manager.command == embedded  # the embedded dispatch command, not a sibling executable
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    try:
        assert client.resources()["capabilities"]["fidelity"] == "l0_only"
        client.load_topology(_L0_TOPOLOGY)
        client.deploy("local-smoke")
        result = client.run_experiment("embedded-1", "local-smoke", _L0_SCENARIO)
        assert result["status"] == "succeeded"
    finally:
        manager.stop()

    # The SQLite store the embedded backend opened persists the experiment across a restart.
    connection = manager.start(timeout=15)
    client = ApiClient(str(connection["url"]), token=str(connection["token"]))
    try:
        listed = {item["experiment_id"]: item for item in client.experiments()}
        assert listed["embedded-1"]["status"] == "succeeded"
    finally:
        manager.stop()
