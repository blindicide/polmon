import pytest
from fastapi.testclient import TestClient

from polmon.backend import app, build_parser
from polmon.client.app import main
from polmon.version import __version__


def test_version_is_current_release() -> None:
    import re

    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)\d+)?", __version__)
    assert match
    major, minor, patch = match.groups()
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


def test_lock_file_names_the_current_version() -> None:
    import tomllib
    from pathlib import Path

    root = Path(__file__).parents[2]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package for package in lock["package"]}
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    # uv.lock sat at 0.2.3 through v0.3.1: refresh it with `uv lock --offline` on every bump.
    assert locked["polmon"]["version"] == project["version"] == __version__


def test_release_metadata_rejects_mismatched_tags_and_scopes_notes():
    import runpy
    from pathlib import Path

    root = Path(__file__).parents[2]
    release = runpy.run_path(str(root / "scripts/release_metadata.py"))
    result = release["metadata"](root, "v0.7.0-rc.2")
    assert result["version"] == __version__
    assert result["prerelease"] is True
    assert result["native_version"] == "0.7.0~rc2"
    assert "Real guest/KVM acceptance: NOT RUN" in result["notes"]
    assert "Experimental prerelease" in result["notes"]
    assert "## [0.6.0]" not in result["notes"]
    assert release["tag_version"]("v0.6.0") == ("0.6.0", False)
    with pytest.raises(ValueError, match="disagree"):
        release["metadata"](root, "v0.7.0")
    with pytest.raises(ValueError, match="expected"):
        release["tag_version"]("v0.7.0rc1")
