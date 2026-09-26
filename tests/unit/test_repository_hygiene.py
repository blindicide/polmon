"""Repository hygiene required by the specification: UTF-8, no mojibake, no operator files."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".sh", ".json", ".csv", ".txt", ".spec"}
# Classic UTF-8-decoded-as-cp1252/latin-1 sequences and the replacement character.
MOJIBAKE = re.compile("Ã[\u0080-¿]|â€|Â[ -¿]|�")
# Files that quote a mojibake defect on purpose, as evidence of what was found and fixed.
MOJIBAKE_QUOTED = {
    "tests/unit/test_repository_hygiene.py",
    "docs/milestones/v0.0.15.md",  # quotes the Windows log line fixed by PYTHONUTF8=1
}
OPERATOR_FILES = {
    "INSTRUCTION.md",
    "RESUME-CLAUDE.md",
    "RESUME-AFTER-QUOTA.md",
    "RUN-ACCOUNTING.md",
    "SUPERVISOR-BRIEF-polmon.md",
}
# Operator/supervisor file families (MANDATE-QT-UI.md, SUPERVISOR-BRIEF-QT-UI.md, ...).
OPERATOR_PATTERNS = tuple(
    re.compile(pattern) for pattern in (r"MANDATE-.*\.md", r"SUPERVISOR-.*\.md", r"RESUME-.*\.md")
)


def tracked_files() -> list[Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("NOT RUN — environment unavailable: not a git checkout")
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [ROOT / name for name in listed.decode("utf-8").split("\0") if name]


def text_files() -> list[Path]:
    return [path for path in tracked_files() if path.suffix in TEXT_SUFFIXES and path.is_file()]


def test_operator_instruction_files_are_never_tracked() -> None:
    tracked = {path.relative_to(ROOT).as_posix() for path in tracked_files()}
    assert not tracked & OPERATOR_FILES
    assert not [name for name in tracked if any(p.fullmatch(name) for p in OPERATOR_PATTERNS)]


def test_text_files_are_utf8_without_bom_or_mojibake() -> None:
    problems = []
    for path in text_files():
        raw = path.read_bytes()
        name = path.relative_to(ROOT).as_posix()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{name}: BOM")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            problems.append(f"{name}: invalid UTF-8 at byte {error.start}")
            continue
        if name not in MOJIBAKE_QUOTED and MOJIBAKE.search(text):
            problems.append(f"{name}: mojibake pattern")
    assert not problems, problems


def test_source_and_docs_have_no_trailing_whitespace_or_doubled_blank_lines() -> None:
    problems = []
    for path in text_files():
        if path.suffix not in {".py", ".md", ".yml", ".yaml", ".toml", ".sh"}:
            continue
        name = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if line != line.rstrip():
                problems.append(f"{name}:{number}: trailing whitespace")
        if path.suffix == ".md" and "\n\n\n" in text:
            problems.append(f"{name}: doubled blank line")
        if text and not text.endswith("\n"):
            problems.append(f"{name}: missing final newline")
    assert not problems, problems


def test_tkinter_is_gone_from_code_and_packaging() -> None:
    """Phase II replaced the Tk client with Qt: no Tk imports, hidden imports or tooling remain."""
    pattern = re.compile(r"^\s*(import tkinter|from tkinter\b)|['\"]tkinter['\"]|\btkinter\.", re.M)
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in text_files()
        if path.suffix in {".py", ".spec", ".toml", ".yml", ".yaml", ".sh"}
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
