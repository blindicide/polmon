"""Validate release tags, canonical package versions and version-scoped notes."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path


def tag_version(tag: str) -> tuple[str, bool]:
    match = re.fullmatch(
        r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)" r"(?:-(alpha|beta|rc)\.([1-9]\d*))?", tag
    )
    if match is None:
        raise ValueError("expected vX.Y.Z or vX.Y.Z-{alpha,beta,rc}.N")
    major, minor, patch, phase, number = match.groups()
    version = f"{major}.{minor}.{patch}"
    if phase:
        version += {"alpha": "a", "beta": "b", "rc": "rc"}[phase] + number
    return version, bool(phase)


def native_version(version: str) -> str:
    """Debian/RPM tilde sorts a preview before its eventual stable version."""
    return re.sub(r"(?<=\d)(a|b|rc)(\d+)$", r"~\1\2", version)


def metadata(root: Path, tag: str) -> dict:
    version, prerelease = tag_version(tag)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((root / "uv.lock").read_text())
    locked = next(p["version"] for p in lock["package"] if p["name"] == "polmon")
    source = re.search(r'__version__ = "([^"]+)"', (root / "src/polmon/version.py").read_text())
    if not source or {source[1], project["version"], locked} != {version}:
        raise ValueError("tag, source, project and lock versions disagree")
    addon = tomllib.loads((root / "addons/l1-vm/pyproject.toml").read_text())["project"]
    if addon["dependencies"] != [f"polmon=={version}"]:
        raise ValueError("addon must pin the exact core candidate")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)",
        changelog,
        flags=re.M | re.S,
    )
    if not section or not section[1].strip():
        raise ValueError("missing nonempty version-scoped changelog section")
    return {
        "tag": tag,
        "version": version,
        "prerelease": prerelease,
        "addon_version": addon["version"],
        "native_version": native_version(version),
        "notes": section[1].strip() + "\n",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--notes-file", type=Path)
    args = parser.parse_args()
    result = metadata(args.root, args.tag)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key in ("version", "prerelease", "addon_version"):
                output.write(f"{key}={str(result[key]).lower()}\n")
    if args.notes_file:
        args.notes_file.write_text(result["notes"], encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
