import pytest
from fastapi.testclient import TestClient

from polmon.backend import app, build_parser
from polmon.client.app import main
from polmon.version import __version__


def test_version_is_current_release() -> None:
    major, minor, patch = __version__.split(".")
    assert (int(major), int(minor), int(patch)) >= (0, 0, 1)


def test_backend_root_exposes_version() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.json() == {"name": "polmon", "version": __version__, "status": "ok"}


def test_backend_parser_defaults_to_loopback() -> None:
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"


def test_client_version_flag(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"polmon {__version__}"


def test_client_self_test_is_headless(capsys) -> None:
    pytest.importorskip("PySide6", reason="NOT RUN — environment unavailable: PySide6 missing")
    assert main(["--self-test"]) == 0
    assert capsys.readouterr().out.rstrip().endswith(f"polmon {__version__} self-test: PASS")


def test_client_without_qt_explains_how_to_install(monkeypatch, capsys) -> None:
    import builtins

    real_import = builtins.__import__

    def no_qt(name, *args, **kwargs):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_qt)
    assert main(["--self-test"]) == 2
    assert "pip install polmon[gui]" in capsys.readouterr().err
