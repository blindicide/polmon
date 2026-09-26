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
    assert manager.log_path is not None and "shutdown_cleanup" in manager.log_tail(10_000)


def test_start_retries_when_selected_port_is_taken(tmp_path, monkeypatch) -> None:
    from polmon.client import local_backend as module

    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    first = int(occupied.getsockname()[1])
    real = module._free_loopback_port
    ports = iter((first, real()))
    monkeypatch.setattr(module, "_free_loopback_port", lambda: next(ports))
    manager = LocalBackendManager(state_directory=tmp_path)
    try:
        connection = manager.start(timeout=5, attempts=2)
        assert connection["port"] != first and manager.running
        assert "address already in use" in manager.log_tail(10_000).lower()
    finally:
        manager.stop()
        occupied.close()
