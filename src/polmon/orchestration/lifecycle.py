"""State machine, rollback, and resource ownership enforcement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from polmon.core.errors import PolmonError
from polmon.orchestration.base import BackendInspection, ExecutionBackend
from polmon.topology.models import Topology


class OrchestrationError(PolmonError):
    code = "orchestration_error"
    status_code = 409


class LifecycleState(StrEnum):
    NEW = "new"
    VALIDATED = "validated"
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class LifecycleInspection:
    topology_id: str
    state: LifecycleState
    owned_resources: frozenset[str]
    backend: BackendInspection


class OwnershipRegistry:
    """Process-local guard against two deployments claiming one OS resource."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._lock = RLock()

    def claim(self, owner: str, resources: set[str]) -> None:
        with self._lock:
            conflicts = {
                resource: self._owners[resource]
                for resource in resources
                if resource in self._owners
            }
            if conflicts:
                raise OrchestrationError(
                    "resource ownership conflict", details={"conflicts": conflicts}
                )
            self._owners.update({resource: owner for resource in resources})

    def release(self, owner: str) -> None:
        with self._lock:
            self._owners = {
                resource: current
                for resource, current in self._owners.items()
                if current != owner
            }

    def resources_for(self, owner: str) -> frozenset[str]:
        with self._lock:
            return frozenset(
                resource for resource, current in self._owners.items() if current == owner
            )


GLOBAL_OWNERSHIP = OwnershipRegistry()


class Orchestrator:
    """Coordinate one topology deployment through a strict, recoverable lifecycle."""

    def __init__(
        self,
        topology: Topology,
        backend: ExecutionBackend,
        *,
        ownership: OwnershipRegistry | None = None,
    ) -> None:
        self.topology = topology
        self.backend = backend
        self.state = LifecycleState.NEW
        self._ownership = ownership or GLOBAL_OWNERSHIP
        self._owner_id = f"{backend.name}:{topology.id}:{id(self)}"

    def _require(self, operation: str, allowed: set[LifecycleState]) -> None:
        if self.state not in allowed:
            raise OrchestrationError(
                f"cannot {operation} topology while lifecycle state is '{self.state}'",
                details={"state": self.state, "allowed": sorted(allowed)},
            )

    def validate(self) -> None:
        if self.state is LifecycleState.VALIDATED:
            return
        self._require("validate", {LifecycleState.NEW})
        self._call("validate", lambda: self.backend.validate(self.topology))
        self.state = LifecycleState.VALIDATED

    def create(self) -> None:
        if self.state is LifecycleState.CREATED:
            return
        self._require("create", {LifecycleState.VALIDATED})
        resources: set[str] = set()
        try:
            resources = self.backend.create(self.topology)
            self._ownership.claim(self._owner_id, resources)
        except Exception as error:
            try:
                self.backend.destroy()
            finally:
                self._ownership.release(self._owner_id)
            raise self._wrap("create", error) from error
        self.state = LifecycleState.CREATED

    def start(self) -> None:
        if self.state is LifecycleState.RUNNING:
            return
        self._require("start", {LifecycleState.CREATED, LifecycleState.STOPPED})
        self._call("start", self.backend.start)
        self.state = LifecycleState.RUNNING

    def stop(self) -> None:
        if self.state in {LifecycleState.STOPPED, LifecycleState.DESTROYED}:
            return
        self._require("stop", {LifecycleState.RUNNING})
        self._call("stop", self.backend.stop)
        self.state = LifecycleState.STOPPED

    def destroy(self) -> None:
        if self.state is LifecycleState.DESTROYED:
            return
        if self.state is LifecycleState.RUNNING:
            self.stop()
        self._require(
            "destroy",
            {
                LifecycleState.NEW,
                LifecycleState.VALIDATED,
                LifecycleState.CREATED,
                LifecycleState.STOPPED,
            },
        )
        try:
            self.backend.destroy()
        except Exception as error:
            raise self._wrap("destroy", error) from error
        finally:
            self._ownership.release(self._owner_id)
        self.state = LifecycleState.DESTROYED

    def inspect(self) -> LifecycleInspection:
        return LifecycleInspection(
            topology_id=self.topology.id,
            state=self.state,
            owned_resources=self._ownership.resources_for(self._owner_id),
            backend=self.backend.inspect(),
        )

    def _call(self, operation: str, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as error:
            raise self._wrap(operation, error) from error

    def _wrap(self, operation: str, error: Exception) -> OrchestrationError:
        if isinstance(error, OrchestrationError):
            return error
        return OrchestrationError(
            f"backend '{self.backend.name}' failed during {operation}",
            details={"operation": operation, "cause": type(error).__name__},
        )
