"""SQLite experiment metadata and session-level telemetry coordination."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from polmon.core.diagnostics import ResourceSnapshot
from polmon.telemetry.models import CaptureSummary, EventCategory, TelemetryEvent
from polmon.telemetry.pcap import BoundedPcapWriter
from polmon.version import __version__

EXPERIMENT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SENSITIVE_KEY = re.compile(r"password|secret|credential|token|api.?key", re.IGNORECASE)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


class TelemetryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                topology_id TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                event TEXT NOT NULL,
                node_id TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_experiment_sequence
                ON events(experiment_id, sequence);
            CREATE TABLE IF NOT EXISTS captures (
                experiment_id TEXT PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                frame_count INTEGER NOT NULL,
                captured_bytes INTEGER NOT NULL,
                dropped_frames INTEGER NOT NULL,
                truncated_frames INTEGER NOT NULL
            );
            """
        )
        self._connection.commit()

    def begin(self, experiment_id: str, topology_id: str, scenario_id: str) -> None:
        if not EXPERIMENT_ID.fullmatch(experiment_id):
            raise ValueError("invalid experiment identifier")
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    experiment_id,
                    __version__,
                    topology_id,
                    scenario_id,
                    datetime.now(UTC).isoformat(),
                    "running",
                ),
            )

    def finish(self, experiment_id: str, status: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE experiments SET finished_at = ?, status = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), status, experiment_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(experiment_id)

    def record(
        self,
        experiment_id: str,
        category: EventCategory,
        event: str,
        *,
        node_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> int:
        timestamp = datetime.now(UTC).isoformat()
        safe_payload = _redact(payload or {})
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """INSERT INTO events
                   (experiment_id, timestamp, category, event, node_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (experiment_id, timestamp, category, event, node_id, _json(safe_payload)),
            )
            return int(cursor.lastrowid)

    def record_resources(self, experiment_id: str, snapshot: ResourceSnapshot) -> int:
        return self.record(
            experiment_id,
            EventCategory.RESOURCE,
            "resource_sample",
            payload=asdict(snapshot),
        )

    def save_capture(self, summary: CaptureSummary) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO captures VALUES (?, ?, ?, ?, ?, ?)",
                (
                    summary.experiment_id,
                    str(summary.path),
                    summary.frame_count,
                    summary.captured_bytes,
                    summary.dropped_frames,
                    summary.truncated_frames,
                ),
            )

    def events(
        self, experiment_id: str, *, after: int = 0, limit: int | None = None
    ) -> list[TelemetryEvent]:
        """Ordered events with ``sequence > after``; ``limit`` bounds one incremental page."""
        query = "SELECT * FROM events WHERE experiment_id = ? AND sequence > ? ORDER BY sequence"
        parameters: tuple[object, ...] = (experiment_id, after)
        if limit is not None:
            query += " LIMIT ?"
            parameters = (*parameters, limit)
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [
            TelemetryEvent(
                row["sequence"],
                row["experiment_id"],
                datetime.fromisoformat(row["timestamp"]),
                EventCategory(row["category"]),
                row["event"],
                row["node_id"],
                json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def experiments(self, limit: int = 200) -> list[dict[str, object]]:
        """Persisted experiments, newest first, each with its capture summary when closed."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT e.*, c.frame_count, c.captured_bytes, c.dropped_frames,
                          c.truncated_frames
                   FROM experiments e LEFT JOIN captures c ON c.experiment_id = e.id
                   ORDER BY e.started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def exists(self, experiment_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        return row is not None

    def experiment(self, experiment_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        capture = self._connection.execute(
            "SELECT * FROM captures WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        return {
            **dict(row),
            "capture": dict(capture) if capture is not None else None,
        }

    def close(self) -> None:
        self._connection.close()


class TelemetrySession:
    def __init__(
        self,
        store: TelemetryStore,
        experiment_id: str,
        topology_id: str,
        scenario_id: str,
        capture_directory: str | Path,
        *,
        max_capture_bytes: int = 1_048_576,
        snaplen: int = 65535,
    ) -> None:
        self.store = store
        self.experiment_id = experiment_id
        self.store.begin(experiment_id, topology_id, scenario_id)
        directory = Path(capture_directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.capture = BoundedPcapWriter(
            experiment_id,
            directory / f"{experiment_id}.pcap",
            max_bytes=max_capture_bytes,
            snaplen=snaplen,
        )
        self.closed = False

    def event(
        self,
        category: EventCategory,
        event: str,
        *,
        node_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> int:
        return self.store.record(
            self.experiment_id, category, event, node_id=node_id, payload=payload
        )

    def packet(self, frame: bytes, *, timestamp: float | None = None) -> bool:
        return self.capture.write(frame, timestamp=timestamp)

    def resources(self, snapshot: ResourceSnapshot) -> int:
        return self.store.record_resources(self.experiment_id, snapshot)

    def close(self, status: str) -> CaptureSummary:
        if self.closed:
            raise RuntimeError("telemetry session is already closed")
        summary = self.capture.close()
        self.store.save_capture(summary)
        self.store.finish(self.experiment_id, status)
        self.closed = True
        return summary
