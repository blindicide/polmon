"""Crash-safe ownership journal for laboratory kernel objects.

Deployment records every generated namespace and link name on disk *before* the privileged batch
that creates them, then records the kernel identities (namespace inode, link ifindex) once they
exist. A backend that dies without its graceful shutdown (SIGKILL, OOM, power loss) leaves that
record behind; the next backend on the same data directory reclaims exactly those objects:

- only entries whose owner process is gone (pid + start time + boot id) are touched;
- only names matching the platform's generated patterns are ever passed to ``ip``;
- after creation, an object is deleted only while its kernel identity still matches the record,
  so a same-named object created later by someone else is reported, never removed;
- processes inside reclaimed namespaces are stopped first (the invoking user's own processes,
  and the ``sudo`` launchers that relay the signal to their root children), so nothing outlives
  the namespace name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import time
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner

NAMESPACE_PATTERN = re.compile(r"^polmon[0-9a-f]{8}n$")
LINK_PATTERN = re.compile(r"^(polmon[0-9a-f]{8}[bt]|veth[0-9a-f]{8}[hp])$")
JOURNAL_VERSION = 1


def boot_id(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def process_start_ticks(pid: int, proc_root: Path = Path("/proc")) -> int | None:
    """Kernel start time of ``pid`` (``/proc/<pid>/stat`` field 22), or None when it is gone."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, IndexError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class LabOwner:
    pid: int
    start_ticks: int | None
    boot_id: str | None

    @classmethod
    def current(cls, proc_root: Path = Path("/proc")) -> LabOwner:
        return cls(os.getpid(), process_start_ticks(os.getpid(), proc_root), boot_id())

    def alive(self, proc_root: Path = Path("/proc"), current_boot: str | None = None) -> bool:
        """True only for the very same process: a reused pid or a reboot reads as dead."""
        if self.boot_id is not None and current_boot is not None and self.boot_id != current_boot:
            return False
        ticks = process_start_ticks(self.pid, proc_root)
        return ticks is not None and (self.start_ticks is None or ticks == self.start_ticks)


class LabJournal:
    """One atomic JSON record per deployed topology under ``directory``."""

    def __init__(
        self,
        directory: str | Path,
        *,
        owner: LabOwner | None = None,
        runner: CommandRunner | None = None,
        proc_root: str | Path = "/proc",
        netns_root: str | Path = "/run/netns",
        sysfs_net_root: str | Path = "/sys/class/net",
        current_boot: str | None = None,
        kill: Callable[[int, int], None] = os.kill,
        grace_seconds: float = 3.0,
    ) -> None:
        self.directory = Path(directory)
        self.proc_root = Path(proc_root)
        self.netns_root = Path(netns_root)
        self.sysfs_net_root = Path(sysfs_net_root)
        self.owner = owner or LabOwner.current(self.proc_root)
        self.current_boot = current_boot if current_boot is not None else boot_id()
        self.runner = runner or CommandRunner()
        self.kill = kill
        self.grace_seconds = grace_seconds

    # -- records ---------------------------------------------------------------------------

    def _path(self, topology_id: str) -> Path:
        digest = hashlib.blake2s(topology_id.encode("utf-8"), digest_size=8).hexdigest()
        return self.directory / f"{digest}.json"

    def _write(self, entry: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(str(entry["topology_id"]))
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        data = json.dumps(entry, sort_keys=True, indent=1).encode("utf-8")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        try:
            directory = os.open(self.directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def get(self, topology_id: str) -> dict[str, object] | None:
        try:
            entry = json.loads(self._path(topology_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return entry if isinstance(entry, dict) else None

    def entries(self) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict) and isinstance(entry.get("topology_id"), str):
                found.append(entry)
        return found

    def record(self, topology_id: str, namespaces: Iterable[str], links: Iterable[str]) -> None:
        """Persist the planned names before any of them is created."""
        namespace_names = sorted(set(namespaces))
        link_names = sorted(set(links))
        unsafe = [name for name in namespace_names if not NAMESPACE_PATTERN.fullmatch(name)]
        unsafe += [name for name in link_names if not LINK_PATTERN.fullmatch(name)]
        if unsafe:
            raise ValueError(f"refusing to journal non-generated laboratory names: {unsafe}")
        if self.get(topology_id) is not None:
            raise RuntimeError(f"laboratory ownership of '{topology_id}' is already journaled")
        self._write(
            {
                "version": JOURNAL_VERSION,
                "topology_id": topology_id,
                "state": "planned",
                "owner": {
                    "pid": self.owner.pid,
                    "start_ticks": self.owner.start_ticks,
                    "boot_id": self.owner.boot_id,
                },
                "recorded_at": time.time(),
                "namespaces": {name: None for name in namespace_names},
                "links": {name: None for name in link_names},
            }
        )

    def _owned_by_me(self, entry: dict[str, object]) -> bool:
        owner = entry.get("owner")
        return isinstance(owner, dict) and owner == {
            "pid": self.owner.pid,
            "start_ticks": self.owner.start_ticks,
            "boot_id": self.owner.boot_id,
        }

    def confirm(self, topology_id: str) -> None:
        """Record the kernel identity of every journaled object that now exists."""
        entry = self.get(topology_id)
        if entry is None or not self._owned_by_me(entry):
            return
        entry["namespaces"] = {
            name: self._namespace_identity(name) for name in dict(entry["namespaces"])
        }
        entry["links"] = {name: self._link_identity(name) for name in dict(entry["links"])}
        entry["state"] = "created"
        self._write(entry)

    def settle(self, topology_id: str) -> bool:
        """Drop our record once none of its objects exists; True when no record of ours is left."""
        entry = self.get(topology_id)
        if entry is None:
            return True
        if not self._owned_by_me(entry):
            return False  # another backend's record: only its owner or recovery may drop it
        if self._present(entry):
            return False
        self._path(topology_id).unlink(missing_ok=True)
        return True

    # -- kernel state ------------------------------------------------------------------------

    def _namespace_identity(self, name: str) -> int | None:
        try:
            return os.stat(self.netns_root / name).st_ino
        except OSError:
            return None

    def _link_identity(self, name: str) -> int | None:
        try:
            return int((self.sysfs_net_root / name / "ifindex").read_text(encoding="ascii"))
        except (OSError, ValueError):
            return None

    def _present(self, entry: dict[str, object]) -> list[str]:
        return [
            name
            for name in dict(entry.get("namespaces", {}))
            if self._namespace_identity(name) is not None
        ] + [name for name in dict(entry.get("links", {})) if self._link_identity(name) is not None]

    def _owned_objects(
        self, entry: dict[str, object]
    ) -> tuple[dict[str, int], list[str], list[str]]:
        """(namespace -> inode, links) still ours, plus same-named foreign objects."""
        created = entry.get("state") == "created"
        namespaces: dict[str, int] = {}
        links: list[str] = []
        foreign: list[str] = []
        for name, recorded in dict(entry.get("namespaces", {})).items():
            if not NAMESPACE_PATTERN.fullmatch(str(name)):
                foreign.append(str(name))
                continue
            current = self._namespace_identity(name)
            if current is None:
                continue
            if created and recorded != current:
                foreign.append(name)
            else:
                namespaces[name] = current
        for name, recorded in dict(entry.get("links", {})).items():
            if not LINK_PATTERN.fullmatch(str(name)):
                foreign.append(str(name))
                continue
            current = self._link_identity(name)
            if current is None:
                continue
            if created and recorded != current:
                foreign.append(name)
            else:
                links.append(name)
        return namespaces, sorted(links), sorted(foreign)

    def _processes(self, namespaces: dict[str, int]) -> tuple[set[int], set[int]]:
        """(launchers, members): ``sudo … ip netns exec <ns>`` and our in-namespace pids."""
        markers = {f"net:[{inode}]" for inode in namespaces.values()}
        launchers: set[int] = set()
        members: set[int] = set()
        try:
            candidates = [item for item in self.proc_root.iterdir() if item.name.isdigit()]
        except OSError:
            return launchers, members
        for directory in candidates:
            pid = int(directory.name)
            if pid == os.getpid():
                continue
            try:
                argv = (directory / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            words = [item.decode("utf-8", "replace") for item in argv if item]
            if words[:1] and Path(words[0]).name == "sudo":
                for index in range(len(words) - 3):
                    if words[index : index + 3] == ["ip", "netns", "exec"] and (
                        words[index + 3] in namespaces
                    ):
                        launchers.add(pid)
                        break
                continue
            try:
                link = os.readlink(directory / "ns" / "net")
            except OSError:
                continue  # another user's (root) process: reached through its sudo launcher
            if link in markers:
                members.add(pid)
        return launchers, members

    def _alive(self, pids: Iterable[int]) -> set[int]:
        return {pid for pid in pids if (self.proc_root / str(pid)).exists()}

    def _stop_processes(self, namespaces: dict[str, int]) -> tuple[int, list[int]]:
        launchers, members = self._processes(namespaces)
        targets = launchers | members
        for pid in sorted(targets):
            with suppress(ProcessLookupError, PermissionError):
                self.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + self.grace_seconds
        remaining = self._alive(targets)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.1)
            remaining = self._alive(remaining)
        # Our own processes can be killed outright; a stuck sudo launcher is never SIGKILLed,
        # because that would orphan its root child instead of stopping it.
        for pid in sorted(remaining & members):
            with suppress(ProcessLookupError, PermissionError):
                self.kill(pid, signal.SIGKILL)
        if remaining & members:
            time.sleep(0.2)
        remaining = self._alive(remaining)
        return len(targets) - len(remaining), sorted(remaining)

    # -- recovery ----------------------------------------------------------------------------

    def reclaimable(
        self, *, keep: Iterable[str] = (), topology_id: str | None = None
    ) -> tuple[list[dict[str, object]], list[str]]:
        """(entries to reclaim, topology ids owned by another live backend)."""
        kept = set(keep)
        reclaim: list[dict[str, object]] = []
        live: list[str] = []
        for entry in self.entries():
            identifier = str(entry["topology_id"])
            if topology_id is not None and identifier != topology_id:
                continue
            if identifier in kept:
                continue
            raw_owner = entry.get("owner") if isinstance(entry.get("owner"), dict) else {}
            try:
                owner = LabOwner(
                    int(raw_owner.get("pid", -1)),  # type: ignore[union-attr]
                    raw_owner.get("start_ticks"),  # type: ignore[union-attr,arg-type]
                    raw_owner.get("boot_id"),  # type: ignore[union-attr,arg-type]
                )
            except (TypeError, ValueError):
                owner = LabOwner(-1, None, None)
            if owner == self.owner:
                reclaim.append(entry)  # ours, but no longer deployed: a failed teardown
            elif owner.pid > 0 and owner.alive(self.proc_root, self.current_boot):
                live.append(identifier)
            else:
                reclaim.append(entry)
        return reclaim, live

    def reconcile(
        self, *, keep: Iterable[str] = (), topology_id: str | None = None
    ) -> dict[str, object]:
        """Reclaim every journaled object whose owning backend is gone (or no longer uses it)."""
        entries, live = self.reclaimable(keep=keep, topology_id=topology_id)
        result: dict[str, object] = {
            "reclaimed": [],
            "skipped_live_owner": live,
            "foreign": [],
            "processes_stopped": 0,
            "processes_remaining": [],
            "failures": [],
        }
        for entry in entries:
            identifier = str(entry["topology_id"])
            namespaces, links, foreign = self._owned_objects(entry)
            stopped, remaining = self._stop_processes(namespaces) if namespaces else (0, [])
            result["processes_stopped"] = int(result["processes_stopped"]) + stopped  # type: ignore[call-overload]
            result["processes_remaining"] += remaining  # type: ignore[operator]
            lines = [f"netns del {name}" for name in sorted(namespaces)]
            lines += [f"link del dev {name}" for name in links]
            if lines:
                self.runner.run(
                    ["ip", "-force", "-batch", "-"],
                    privileged=True,
                    check=False,
                    timeout=10 + len(lines),
                    input="".join(f"{line}\n" for line in lines),
                )
            still = [name for name in namespaces if self._namespace_identity(name) is not None]
            still += [name for name in links if self._link_identity(name) is not None]
            if still:
                result["failures"].append({"topology_id": identifier, "remaining": still})  # type: ignore[union-attr]
                continue
            if foreign:
                result["foreign"].append({"topology_id": identifier, "names": foreign})  # type: ignore[union-attr]
            self._path(identifier).unlink(missing_ok=True)
            result["reclaimed"].append(  # type: ignore[union-attr]
                {
                    "topology_id": identifier,
                    "namespaces": sorted(namespaces),
                    "links": links,
                    "owner_pid": dict(entry.get("owner") or {}).get("pid"),
                }
            )
        return result
