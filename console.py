"""Bounded interactive SSH sessions and retained transcripts."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from threading import Event, RLock, Thread

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.core.errors import ConfigurationError

MAX_SESSION_BUFFER_BYTES = 524_288
MAX_INPUT_BYTES = 4096
IDLE_TIMEOUT_SECONDS = 900


class ConsoleSession:
    def __init__(
        self,
        session_id: str,
        topology_id: str,
        node_id: str,
        backend: NamespaceBackend,
        transcript: Path,
    ) -> None:
        self.id = session_id
        self.topology_id = topology_id
        self.node_id = node_id
        self.transcript = transcript
        self.created_at = time.time()
        self.last_activity = self.created_at
        self.sequence = 0
        self.size = 0
        self.buffer: deque[tuple[int, str, int]] = deque()
        self.lock = RLock()
        command = ["sudo", "-n", *backend.ssh_argv(node_id, interactive=True)]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        transcript.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.reader = Thread(target=self._read, daemon=True, name=f"console-{session_id}")
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        with self.transcript.open("ab") as stream:
            os.chmod(self.transcript, 0o600)
            while chunk := self.process.stdout.read(4096):
                stream.write(chunk)
                stream.flush()
                text = chunk.decode("utf-8", "replace")
                with self.lock:
                    self.sequence += 1
                    self.buffer.append((self.sequence, text, len(chunk)))
                    self.size += len(chunk)
                    self.last_activity = time.time()
                    while self.size > MAX_SESSION_BUFFER_BYTES and self.buffer:
                        _, _, removed = self.buffer.popleft()
                        self.size -= removed

    def input(self, data: str) -> None:
        encoded = data.encode("utf-8")
        if not encoded or len(encoded) > MAX_INPUT_BYTES:
            raise ConfigurationError(
                "console input must contain 1 to 4096 UTF-8 bytes",
                message_code="console.input_size",
            )
        if self.process.poll() is not None or self.process.stdin is None:
            raise ConfigurationError(
                "console session is no longer running", message_code="console.session_closed"
            )
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise ConfigurationError(
                "console session input failed", message_code="console.session_closed"
            ) from error
        self.last_activity = time.time()

    def snapshot(self, after: int = 0) -> dict[str, object]:
        with self.lock:
            output = "".join(text for sequence, text, _ in self.buffer if sequence > after)
            cursor = self.sequence
            oldest = self.buffer[0][0] if self.buffer else cursor
        return {
            "session_id": self.id,
            "topology_id": self.topology_id,
            "node_id": self.node_id,
            "state": "running" if self.process.poll() is None else "closed",
            "exit_status": self.process.poll(),
            "cursor": cursor,
            "oldest_cursor": oldest,
            "output": output,
            "transcript": str(self.transcript),
        }

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=3)
            except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    self.process.kill()
        self.reader.join(timeout=3)


class ConsoleSessions:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.sessions: dict[str, ConsoleSession] = {}
        self.lock = RLock()
        self.stopping = Event()
        self.sweeper = Thread(target=self._sweep, daemon=True, name="console-sweeper")
        self.sweeper.start()

    def create(
        self, topology_id: str, node_id: str, backend: NamespaceBackend
    ) -> dict[str, object]:
        session_id = secrets.token_hex(6)
        transcript = self.directory / topology_id / node_id / f"{session_id}.log"
        session = ConsoleSession(session_id, topology_id, node_id, backend, transcript)
        with self.lock:
            self.sessions[session_id] = session
        return session.snapshot()

    def get(self, session_id: str, after: int = 0) -> dict[str, object]:
        return self._session(session_id).snapshot(after)

    def input(self, session_id: str, data: str) -> dict[str, object]:
        session = self._session(session_id)
        session.input(data)
        return session.snapshot()

    def delete(self, session_id: str) -> dict[str, object]:
        with self.lock:
            session = self.sessions.pop(session_id, None)
        if session is None:
            raise ConfigurationError(
                "console session was not found", message_code="console.session_unknown"
            )
        session.close()
        return {"session_id": session_id, "state": "closed"}

    def close_topology(self, topology_id: str) -> None:
        with self.lock:
            ids = [key for key, value in self.sessions.items() if value.topology_id == topology_id]
        for session_id in ids:
            self.delete(session_id)

    def close(self) -> None:
        self.stopping.set()
        with self.lock:
            ids = list(self.sessions)
        for session_id in ids:
            self.delete(session_id)
        self.sweeper.join(timeout=2)

    def _session(self, session_id: str) -> ConsoleSession:
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ConfigurationError(
                "console session was not found", message_code="console.session_unknown"
            )
        return session

    def _sweep(self) -> None:
        while not self.stopping.wait(5):
            now = time.time()
            with self.lock:
                expired = [
                    key
                    for key, session in self.sessions.items()
                    if now - session.last_activity > IDLE_TIMEOUT_SECONDS
                ]
            for session_id in expired:
                self.delete(session_id)
