"""Persistence guarantees shared by the Windows and POSIX clients."""

import os
from types import SimpleNamespace

import pytest

from polmon import library


def _library(tmp_path):
    return library.YamlLibrary(
        tmp_path,
        parse=lambda value: value,
        dump=lambda value: value,
        identity=lambda _value: "sample",
    )


def test_windows_put_flushes_file_and_skips_directory_open(tmp_path, monkeypatch) -> None:
    documents = _library(tmp_path)
    destination = documents.put("sample", "old\n")
    synced: list[int] = []

    def sync_file(fd: int) -> None:
        synced.append(fd)
        os.fsync(fd)

    def unexpected_directory_open(*_args, **_kwargs):
        raise AssertionError("Windows must not open a directory for fsync")

    monkeypatch.setattr(
        library,
        "os",
        SimpleNamespace(
            name="nt",
            getpid=os.getpid,
            fsync=sync_file,
            open=unexpected_directory_open,
        ),
    )

    assert documents.put("sample", "new\n") == destination
    assert destination.read_text(encoding="utf-8") == "new\n"
    assert len(synced) == 1
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory fsync requires POSIX")
def test_posix_put_syncs_file_and_directory_after_replace(tmp_path, monkeypatch) -> None:
    documents = _library(tmp_path)
    events: list[str] = []

    def open_directory(path, flags):
        assert path == tmp_path
        assert flags == os.O_RDONLY
        events.append("open_directory")
        return os.open(path, flags)

    def sync(fd: int) -> None:
        events.append("sync")
        os.fsync(fd)

    def close(fd: int) -> None:
        events.append("close_directory")
        os.close(fd)

    monkeypatch.setattr(
        library,
        "os",
        SimpleNamespace(
            name="posix",
            getpid=os.getpid,
            fsync=sync,
            open=open_directory,
            close=close,
            O_RDONLY=os.O_RDONLY,
        ),
    )

    destination = documents.put("sample", "content\n")
    assert destination.read_text(encoding="utf-8") == "content\n"
    assert events == ["sync", "open_directory", "sync", "close_directory"]
    assert not list(tmp_path.glob(".*.tmp"))
