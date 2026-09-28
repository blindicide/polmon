"""Bounded structured laboratory logs with a memory ring and rotating JSONL files."""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
MAX_TEXT = 2_000
MAX_PARAM_ITEMS = 32


def _safe(value: object, *, limit: int = MAX_TEXT, key: str = "") -> object:
    """Make log payloads JSON-safe, bounded, and free of credential-like values."""
    if any(word in key.casefold() for word in ("token", "password", "secret", "private_key")):
        return "[redacted]"
    if isinstance(value, str):
        return value[:limit] + ("…" if len(value) > limit else "")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict):
        return {
            str(item_key): _safe(item_value, key=str(item_key))
            for item_key, item_value in list(value.items())[:MAX_PARAM_ITEMS]
        }
    if isinstance(value, list | tuple | set):
        return [_safe(item) for item in list(value)[:MAX_PARAM_ITEMS]]
    return _safe(str(value), limit=limit)


class StructuredLogStore:
    """Append structured records to a bounded ring and rotating JSONL files.

    The store is intentionally independent of Python's root logger: lab events have a stable
    schema and never inherit arbitrary exception or request content. Files are loaded only up to
    the configured ring capacity on restart, so reads remain bounded.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        max_records: int = 5_000,
        max_file_bytes: int = 256 * 1024,
        max_files: int = 5,
    ) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "polmon.jsonl"
        self.max_records = max_records
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self._records: deque[dict[str, object]] = deque(maxlen=max_records)
        self._cursor = 0
        self._condition = threading.Condition()
        self._load_recent()

    def _load_recent(self) -> None:
        paths = [self.directory / f"polmon.jsonl.{index}" for index in range(self.max_files, 0, -1)]
        paths.append(self.path)
        for path in paths:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()[-self.max_records :]
            except OSError:
                continue
            for line in lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict) and isinstance(item.get("cursor"), int):
                    self._records.append(item)
                    self._cursor = max(self._cursor, int(item["cursor"]))

    def emit(
        self,
        level: str,
        event: str,
        message: str,
        *,
        params: dict[str, object] | None = None,
        deployment: str | None = None,
        topology: str | None = None,
        node: dict[str, object] | None = None,
        experiment: str | None = None,
        session: str | None = None,
        logger: str = "polmon.lab",
    ) -> dict[str, object]:
        normalized = level.upper()
        if normalized not in LEVELS:
            raise ValueError(f"unknown log level {level!r}")
        with self._condition:
            self._cursor += 1
            correlation: dict[str, object] = {}
            for key, value in (
                ("deployment", deployment),
                ("topology", topology),
                ("experiment", experiment),
                ("session", session),
            ):
                if value is not None:
                    correlation[key] = _safe(value, limit=128)
            if node is not None:
                correlation["node"] = _safe(node, limit=256)
            record: dict[str, object] = {
                "cursor": self._cursor,
                "timestamp": datetime.now(UTC).isoformat(),
                "level": normalized,
                "logger": logger,
                "event": event[:128],
                "message": _safe(message, limit=MAX_TEXT),
                "params": _safe(params or {}, limit=MAX_TEXT),
                "correlation": correlation,
            }
            encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._rotate_if_needed(len(encoded))
            try:
                with self.path.open("ab") as stream:
                    stream.write(encoded)
            except OSError:
                # In-memory records remain useful if the data directory becomes read-only.
                pass
            self._records.append(record)
            self._condition.notify_all()
            return record

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        if size + incoming <= self.max_file_bytes:
            return
        for index in range(self.max_files - 1, 0, -1):
            source = self.directory / f"polmon.jsonl.{index}"
            destination = self.directory / f"polmon.jsonl.{index + 1}"
            try:
                if index == self.max_files - 1 and destination.exists():
                    destination.unlink()
                if source.exists():
                    source.replace(destination)
            except OSError:
                pass
        try:
            if self.path.exists():
                self.path.replace(self.directory / "polmon.jsonl.1")
        except OSError:
            pass

    @staticmethod
    def _node_matches(node: object, query: str) -> bool:
        if not isinstance(node, dict):
            return False
        values = " ".join(str(node.get(key, "")) for key in ("id", "name", "uuid"))
        return query.casefold() in values.casefold()

    def query(
        self,
        *,
        level: str | None = None,
        source: str | None = None,
        deployment: str | None = None,
        topology: str | None = None,
        node: str | None = None,
        session: str | None = None,
        experiment: str | None = None,
        search: str | None = None,
        since: int = 0,
        limit: int = 200,
    ) -> dict[str, object]:
        threshold = LEVELS.get((level or "DEBUG").upper(), 10)
        with self._condition:
            records = list(self._records)
        selected: list[dict[str, object]] = []
        for record in records:
            if int(record.get("cursor", 0)) <= since:
                continue
            if LEVELS.get(str(record.get("level")), 0) < threshold:
                continue
            if source and source.casefold() not in str(record.get("logger", "")).casefold():
                continue
            correlation = record.get("correlation")
            if not isinstance(correlation, dict):
                continue
            if deployment and correlation.get("deployment") != deployment:
                continue
            if topology and correlation.get("topology") != topology:
                continue
            if session and correlation.get("session") != session:
                continue
            if experiment and correlation.get("experiment") != experiment:
                continue
            if node and not self._node_matches(correlation.get("node"), node):
                continue
            if search:
                haystack = json.dumps(record, ensure_ascii=False).casefold()
                if search.casefold() not in haystack:
                    continue
            selected.append(record)
        selected = selected[: max(1, min(limit, 500))]
        return {
            "records": selected,
            "next_cursor": int(selected[-1]["cursor"]) if selected else since,
            "has_more": len(selected) < len(records),
        }

    def wait_for(self, since: int, timeout: float = 1.0) -> dict[str, object]:
        with self._condition:
            self._condition.wait_for(lambda: self._cursor > since, timeout=max(0.0, timeout))
        return self.query(since=since, limit=100)

    def files(self) -> dict[str, object]:
        files = []
        for path in sorted(self.directory.rglob("*")):
            if not path.is_file():
                continue
            try:
                files.append({"path": str(path), "size": path.stat().st_size})
            except OSError:
                continue
        return {
            "directory": str(self.directory),
            "files": files,
            "max_file_bytes": self.max_file_bytes,
        }

    def last_errors(self, limit: int = 20) -> list[dict[str, object]]:
        return [
            item
            for item in reversed(list(self._records))
            if LEVELS.get(str(item.get("level")), 0) >= LEVELS["ERROR"]
        ][: max(1, min(limit, 100))]
