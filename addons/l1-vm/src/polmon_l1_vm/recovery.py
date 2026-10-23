"""Журнал владения запуском ВМ и восстановление после аварийного завершения."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner
from polmon_l1_vm.host import alive, terminate
from polmon_l1_vm.images import VMError
from polmon_l1_vm.lab import release

STATE_NAME = "state.json"
STATE_VERSION = 1
SOCKET_PREFIX = "pmvm-"
OWNED_FILE = re.compile(r"[a-z][a-z0-9-]{0,31}(\.qcow2|-seed\.iso)")


def write_state(directory: Path, state: dict) -> None:
    """Атомарно записывает журнал: частично записанный файл не должен подменять прежний."""
    path = directory / STATE_NAME
    temporary = directory / f".{STATE_NAME}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"version": STATE_VERSION, **state}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_state(directory: Path) -> dict | None:
    path = directory / STATE_NAME
    if path.is_symlink() or not path.is_file():
        return None
    if path.stat().st_size > 65_536:
        raise VMError("vm.state_invalid")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise VMError("vm.state_invalid") from error
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise VMError("vm.state_invalid")
    return state


def _owned_files(directory: Path, state: dict) -> list[Path]:
    """Только файлы в каталоге запуска с ожидаемыми именами: журнал не даёт права удалять чужое."""
    found = []
    for name in state.get("files", []):
        path = directory / str(name)
        if OWNED_FILE.fullmatch(str(name)) and path.parent == directory:
            found.append(path)
    return found


def _socket_dir(state: dict) -> Path | None:
    value = state.get("socket_dir")
    if not value:
        return None
    path = Path(value)
    if (
        path.parent != Path(os.path.realpath(path.parent))
        or not path.name.startswith(SOCKET_PREFIX)
        or path.is_symlink()
    ):
        raise VMError("vm.state_invalid")
    return path


def inspect_run(directory: Path) -> dict:
    """Описывает записанное владение и то, что из него ещё живо; ничего не меняет."""
    state = read_state(directory.resolve())
    if state is None:
        return {"state": "absent", "processes": {}, "files": []}
    return {
        "state": "present",
        "mode": state.get("mode"),
        "processes": {
            node: {"pid": identity[0], "alive": alive(identity)}
            for node, identity in state.get("processes", {}).items()
        },
        "holder_alive": bool(state.get("holder") and alive(state["holder"])),
        "files": [str(path.name) for path in _owned_files(directory.resolve(), state)],
    }


def recover(directory: Path, runner: CommandRunner | None = None) -> dict:
    """Останавливает записанные процессы, снимает пространство, удаляет файлы запуска."""
    directory = directory.resolve()
    runner = runner or CommandRunner()
    state = read_state(directory)
    if state is None:
        return {"recovered": False, "processes": [], "released": [], "files": []}
    stopped = [
        node
        for node, identity in state.get("processes", {}).items()
        if terminate(identity, grace=3)
    ]
    released = release(state, runner)
    removed = []
    for path in _owned_files(directory, state):
        if path.exists() or path.is_symlink():
            path.unlink()
            removed.append(path.name)
    socket_dir = _socket_dir(state)
    if socket_dir is not None and socket_dir.is_dir():
        shutil.rmtree(socket_dir, ignore_errors=True)
    for name in state.get("pidfiles", []):
        if re.fullmatch(r"[a-z][a-z0-9-]{0,31}\.pid", str(name)):
            (directory / name).unlink(missing_ok=True)
    with contextlib.suppress(FileNotFoundError):
        (directory / STATE_NAME).unlink()
    return {"recovered": True, "processes": stopped, "released": released, "files": removed}
