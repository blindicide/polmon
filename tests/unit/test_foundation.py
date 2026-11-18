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


def test_release_metadata_checks_scoped_notes_versions_and_addon_pin(tmp_path):
    import re
    import runpy
    import shutil
    from pathlib import Path

    root = Path(__file__).parents[2]
    release = runpy.run_path(str(root / "scripts/release_metadata.py"))
    version = "0.7.2"
    result = release["metadata"](root, f"v{version}")
    notes = result["notes"]
    assert result["version"] == __version__ == version
    assert result["prerelease"] is False
    assert result["addon_version"] == "0.1.1"
    assert result["native_version"] == version
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)",
        changelog,
        flags=re.M | re.S,
    )
    assert section is not None
    assert notes == section[1].strip() + "\n"
    assert f"## [{version}]" not in notes
    assert "integration_verified" in notes

    assert release["tag_version"](f"v{version}") == (version, False)
    assert release["tag_version"](f"v{version}-rc.1") == (f"{version}rc1", True)
    assert release["native_version"](f"{version}rc1") == f"{version}~rc1"
    with pytest.raises(ValueError, match="disagree"):
        release["metadata"](root, f"v{version}-rc.1")
    with pytest.raises(ValueError, match="disagree"):
        release["metadata"](root, "v0.7.1")
    assert release["tag_version"]("v0.6.0") == ("0.6.0", False)
    with pytest.raises(ValueError, match="expected"):
        release["tag_version"](f"v{version}rc1")

    altered = tmp_path / "project"
    required = (
        "pyproject.toml",
        "uv.lock",
        "src/polmon/version.py",
        "addons/l1-vm/pyproject.toml",
        "CHANGELOG.md",
    )
    for relative in required:
        source = root / relative
        target = altered / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    addon = altered / "addons/l1-vm/pyproject.toml"
    addon.write_text(
        addon.read_text(encoding="utf-8").replace(
            f"polmon=={version}", "polmon==0.7.1"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="addon must pin"):
        release["metadata"](altered, f"v{version}")
