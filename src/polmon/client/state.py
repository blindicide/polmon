"""Shared client session state; pages observe it through signals (GUI thread only)."""

from __future__ import annotations

import sys
import time
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from polmon.client.api import DEFAULT_TIMEOUT, DEFAULT_URL, ApiClient
from polmon.client.errors import Problem


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    UNAUTHORIZED = "unauthorized"
    LOST = "lost"


class Session(QObject):
    connection_changed = Signal()
    resources_changed = Signal()
    topologies_changed = Signal()
    deployments_changed = Signal()
    experiments_changed = Signal()
    busy_changed = Signal()
    logged = Signal(str, object)  # level, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = DEFAULT_URL
        self.token = ""  # memory only; never persisted or logged
        self.timeout = DEFAULT_TIMEOUT
        self.state = ConnectionState.DISCONNECTED
        self.backend_version: str | None = None
        self.connection_kind = "local" if sys.platform == "win32" else "remote"
        self.capabilities: dict[str, object] = {}
        self.latency: float | None = None
        self.lost_since: float | None = None
        self.problem: Problem | None = None
        self.resources: dict[str, object] | None = None
        self.backend_topologies: list[dict[str, object]] = []
        self.deployments: dict[str, dict[str, object]] = {}
        self.experiments: list[dict[str, object]] = []
        self.active_experiment: str | None = None
        self.active_benchmark: str | None = None
        # Topologies this client loaded; polled directly when the backend cannot list them.
        self.known_topologies: set[str] = set()
        # Features the connected backend does not provide (older backend version).
        self.unsupported: set[str] = set()

    # -- connection ---------------------------------------------------------------------------

    def client(self, *, timeout: float | None = None) -> ApiClient:
        """Build a client from the current settings (call on the GUI thread)."""
        return ApiClient(self.url, timeout=timeout or self.timeout, token=self.token or None)

    @property
    def connected(self) -> bool:
        return self.state is ConnectionState.CONNECTED

    def set_state(self, state: ConnectionState, problem: Problem | None = None) -> None:
        previous = self.state
        self.state = state
        self.problem = problem
        if state is ConnectionState.LOST and previous is not ConnectionState.LOST:
            self.lost_since = time.time()
        elif state is not ConnectionState.LOST:
            self.lost_since = None
        if state is ConnectionState.DISCONNECTED:
            self.unsupported = set()
            self.backend_version = None
            self.capabilities = {}
            self.latency = None
            self.resources = None
            self.backend_topologies = []
            self.deployments = {}
        self.connection_changed.emit()

    # -- data ---------------------------------------------------------------------------------

    def set_resources(self, resources: dict[str, object]) -> None:
        self.resources = resources
        self.resources_changed.emit()

    def set_topologies(self, topologies: list[dict[str, object]]) -> None:
        if topologies != self.backend_topologies:
            self.backend_topologies = topologies
            self.topologies_changed.emit()

    def set_deployments(self, deployments: dict[str, dict[str, object]]) -> None:
        if deployments != self.deployments:
            self.deployments = deployments
            self.deployments_changed.emit()

    def set_experiments(self, experiments: list[dict[str, object]]) -> None:
        if experiments != self.experiments:
            self.experiments = experiments
            self.experiments_changed.emit()

    def deployed(self, topology_id: str | None) -> bool:
        return bool(topology_id) and topology_id in self.deployments

    def loaded(self, topology_id: str | None) -> bool:
        return any(item.get("topology_id") == topology_id for item in self.backend_topologies)

    def log(self, message: object, level: str = "info") -> None:
        """Append to the activity log. ``message`` (a ``Msg``, a ``Problem`` or verbatim text)
        is rendered on display, so the log follows a language switch."""
        self.logged.emit(level, message)

    def limits(self) -> dict[str, object]:
        limits = (self.resources or {}).get("limits")
        return limits if isinstance(limits, dict) else {}

    @property
    def local_backend(self) -> bool:
        return self.connection_kind == "local"

    @property
    def l0_only(self) -> bool:
        return self.capabilities.get("fidelity") == "l0_only" or self.local_backend
