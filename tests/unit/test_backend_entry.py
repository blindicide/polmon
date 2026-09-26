import sqlite3
import subprocess
import sys

import pytest

import polmon.backend as backend
from polmon.api.control import ControlPlane
from polmon.version import __version__


def test_backend_self_test_releases_its_database_before_cleanup(monkeypatch, capsys) -> None:
    planes: list[ControlPlane] = []

    class RecordingPlane(ControlPlane):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            planes.append(self)

    monkeypatch.setattr(backend, "ControlPlane", RecordingPlane)
    assert backend.main(["--self-test"]) == 0
    output = capsys.readouterr().out.rstrip()
    assert output.endswith(f"polmon {__version__} backend self-test: PASS")
    # Windows refuses to delete an open SQLite file (WinError 32): the handle must be closed.
    assert len(planes) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        planes[0].telemetry._connection.execute("SELECT 1")


def test_backend_self_test_closes_the_database_when_the_workflow_fails(
    monkeypatch, capsys
) -> None:
    planes: list[ControlPlane] = []

    class FailingPlane(ControlPlane):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            planes.append(self)

        def deploy(self, topology_id: str) -> dict[str, object]:
            raise RuntimeError("deploy exploded")

    monkeypatch.setattr(backend, "ControlPlane", FailingPlane)
    assert backend.main(["--self-test"]) == 1
    assert "FAIL RuntimeError: deploy exploded" in capsys.readouterr().out
    with pytest.raises(sqlite3.ProgrammingError):
        planes[0].telemetry._connection.execute("SELECT 1")


def test_importing_the_backend_creates_no_state_in_the_working_directory(tmp_path) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import polmon.backend; print(polmon.backend.__version__)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert completed.stdout.strip() == __version__
    assert list(tmp_path.iterdir()) == []


def test_default_app_is_built_once_on_first_access() -> None:
    assert backend.app is backend.app
    with pytest.raises(AttributeError):
        backend.not_an_attribute  # noqa: B018
