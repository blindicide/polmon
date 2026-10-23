"""Crash-safe lab ownership journal: atomic records, owner liveness, safe reclamation."""

import json
import os
import shutil
import signal
from pathlib import Path

import pytest

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.journal import (
    LINK_PATTERN,
    NAMESPACE_PATTERN,
    LabJournal,
    LabOwner,
)
from polmon.backends.namespace.runner import CommandResult

NS_A = "polmon0000000an"
NS_B = "polmon0000000bn"
BRIDGE = "polmon000000c0b"
VETH = "veth0000000dh"


class FakeKernel:
    """Fake /proc, /run/netns and /sys/class/net trees driven by a recording ``ip`` runner."""

    def __init__(self, root: Path) -> None:
        self.proc = root / "proc"
        self.netns = root / "netns"
        self.sysfs = root / "sys"
        for path in (self.proc, self.netns, self.sysfs):
            path.mkdir()
        self.batches: list[str] = []
        self.signals: list[tuple[int, int]] = []
        self.ignore_term: set[int] = set()
        self.ifindex = 100
        self.delete_fails = False

    def add_namespace(self, name: str) -> int:
        path = self.netns / name
        path.write_text("")
        return os.stat(path).st_ino

    def add_link(self, name: str) -> None:
        self.ifindex += 1
        (self.sysfs / name).mkdir()
        (self.sysfs / name / "ifindex").write_text(f"{self.ifindex}\n")

    def add_process(self, pid: int, argv: list[str], *, netns_inode: int | None = None) -> None:
        directory = self.proc / str(pid)
        (directory / "ns").mkdir(parents=True)
        (directory / "cmdline").write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")
        (directory / "stat").write_text(f"{pid} (x) S " + " ".join(["1"] * 18) + " 4242 0\n")
        if netns_inode is not None:
            os.symlink(f"net:[{netns_inode}]", directory / "ns" / "net")

    def kill(self, pid: int, number: int) -> None:
        self.signals.append((pid, number))
        if number == signal.SIGTERM and pid in self.ignore_term:
            return
        shutil.rmtree(self.proc / str(pid), ignore_errors=True)

    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):  # noqa: A002
        assert privileged and command == ["ip", "-force", "-batch", "-"]
        self.batches.append(input)
        if not self.delete_fails:
            for line in input.splitlines():
                name = line.split()[-1]
                (self.netns / name).unlink(missing_ok=True)
                shutil.rmtree(self.sysfs / name, ignore_errors=True)
        return CommandResult("", "", 0)

    def journal(self, directory: Path, owner: LabOwner) -> LabJournal:
        return LabJournal(
            directory,
            owner=owner,
            runner=self,  # type: ignore[arg-type]
            proc_root=self.proc,
            netns_root=self.netns,
            sysfs_net_root=self.sysfs,
            current_boot="boot-1",
            kill=self.kill,
            grace_seconds=0.2,
        )


@pytest.fixture
def kernel(tmp_path):
    return FakeKernel(tmp_path)


DEAD = LabOwner(pid=999_999, start_ticks=1, boot_id="boot-1")
ME = LabOwner(pid=10, start_ticks=4242, boot_id="boot-1")


def crashed_deployment(kernel: FakeKernel, directory: Path) -> LabJournal:
    old = kernel.journal(directory, DEAD)
    old.record("lab", [NS_A, NS_B], [BRIDGE, VETH])
    kernel.add_namespace(NS_A)
    kernel.add_namespace(NS_B)
    kernel.add_link(BRIDGE)
    kernel.add_link(VETH)
    old.confirm("lab")
    return kernel.journal(directory, ME)


def test_record_is_atomic_private_and_refuses_unsafe_names(kernel, tmp_path) -> None:
    journal = kernel.journal(tmp_path / "j", ME)
    with pytest.raises(ValueError, match="non-generated"):
        journal.record("lab", ["ens3"], [])
    with pytest.raises(ValueError, match="non-generated"):
        journal.record("lab", [NS_A], ["tailscale0"])
    journal.record("lab", [NS_A], [BRIDGE])
    files = list((tmp_path / "j").iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"
    assert files[0].stat().st_mode & 0o777 == 0o600
    entry = json.loads(files[0].read_text())
    assert entry["state"] == "planned" and entry["owner"]["pid"] == ME.pid
    with pytest.raises(RuntimeError, match="already journaled"):
        journal.record("lab", [NS_A], [])


def test_owner_liveness_uses_start_time_and_boot(kernel) -> None:
    kernel.add_process(77, ["polmon-backend"])
    assert LabOwner(77, 4242, "boot-1").alive(kernel.proc, "boot-1")
    assert not LabOwner(77, 1, "boot-1").alive(kernel.proc, "boot-1")  # pid reused
    assert not LabOwner(77, 4242, "boot-0").alive(kernel.proc, "boot-1")  # rebooted
    assert not LabOwner(78, 4242, "boot-1").alive(kernel.proc, "boot-1")


def test_reconcile_reclaims_dead_owner_objects_and_processes(kernel, tmp_path) -> None:
    journal = crashed_deployment(kernel, tmp_path / "j")
    inode = os.stat(kernel.netns / NS_A).st_ino
    kernel.add_process(500, ["/usr/bin/python3", "static_http.py"], netns_inode=inode)
    kernel.add_process(501, ["sudo", "-n", "ip", "netns", "exec", NS_B, "/usr/sbin/sshd", "-D"])
    kernel.add_process(502, ["sudo", "-n", "ip", "netns", "exec", "otherns", "sleep"])
    kernel.add_process(503, ["/usr/bin/bash"], netns_inode=4026531840)  # host namespace

    result = journal.reconcile()

    assert [item["topology_id"] for item in result["reclaimed"]] == ["lab"]
    assert result["failures"] == [] and result["foreign"] == []
    assert result["processes_stopped"] == 2 and result["processes_remaining"] == []
    assert sorted(pid for pid, _ in kernel.signals) == [500, 501]
    assert sorted(kernel.batches[0].splitlines()) == sorted(
        [f"netns del {NS_A}", f"netns del {NS_B}", f"link del dev {BRIDGE}", f"link del dev {VETH}"]
    )
    assert journal.entries() == []
    assert (kernel.proc / "502").exists() and (kernel.proc / "503").exists()
    assert journal.reconcile()["reclaimed"] == []  # idempotent: nothing left to do


def test_reconcile_never_touches_live_owner_or_kept_deployments(kernel, tmp_path) -> None:
    other = LabOwner(77, 4242, "boot-1")
    kernel.add_process(77, ["polmon-backend"])
    kernel.journal(tmp_path / "j", other).record("theirs", [NS_A], [])
    kernel.add_namespace(NS_A)
    mine = kernel.journal(tmp_path / "j", ME)
    mine.record("mine", [NS_B], [])
    kernel.add_namespace(NS_B)

    result = mine.reconcile(keep={"mine"})

    assert result["skipped_live_owner"] == ["theirs"] and result["reclaimed"] == []
    assert kernel.batches == [] and len(mine.entries()) == 2


def test_created_objects_with_changed_identity_are_foreign(kernel, tmp_path) -> None:
    journal = crashed_deployment(kernel, tmp_path / "j")
    # Someone removed the leftovers and an unrelated object reused two of the names.
    shutil.rmtree(kernel.sysfs / BRIDGE)
    kernel.add_link(BRIDGE)
    (kernel.netns / NS_B).unlink()
    (kernel.netns / "spacer").write_text("")  # make sure the new inode differs
    kernel.add_namespace(NS_B)

    result = journal.reconcile()

    batch = kernel.batches[0]
    assert BRIDGE not in batch and NS_B not in batch
    assert f"netns del {NS_A}" in batch and f"link del dev {VETH}" in batch
    assert result["foreign"] == [{"topology_id": "lab", "names": sorted([BRIDGE, NS_B])}]
    assert (kernel.sysfs / BRIDGE).exists() and (kernel.netns / NS_B).exists()


def test_planned_entry_from_interrupted_create_is_reclaimed_by_name(kernel, tmp_path) -> None:
    kernel.journal(tmp_path / "j", DEAD).record("lab", [NS_A, NS_B], [BRIDGE])
    kernel.add_namespace(NS_A)  # the batch died after the first object
    result = kernel.journal(tmp_path / "j", ME).reconcile()
    assert result["reclaimed"][0]["namespaces"] == [NS_A]
    assert kernel.batches == [f"netns del {NS_A}\n"]


def test_failed_delete_keeps_the_record_for_the_next_attempt(kernel, tmp_path) -> None:
    journal = crashed_deployment(kernel, tmp_path / "j")
    kernel.delete_fails = True
    result = journal.reconcile()
    assert result["reclaimed"] == [] and result["failures"][0]["topology_id"] == "lab"
    assert len(journal.entries()) == 1
    kernel.delete_fails = False
    assert journal.reconcile()["reclaimed"][0]["topology_id"] == "lab"


def test_stuck_launcher_is_never_sigkilled(kernel, tmp_path) -> None:
    journal = crashed_deployment(kernel, tmp_path / "j")
    kernel.add_process(600, ["sudo", "-n", "ip", "netns", "exec", NS_A, "sshd"])
    inode = os.stat(kernel.netns / NS_A).st_ino
    kernel.add_process(601, ["xclock"], netns_inode=inode)
    kernel.ignore_term.update({600, 601})
    result = journal.reconcile()
    assert (600, signal.SIGKILL) not in kernel.signals
    assert (601, signal.SIGKILL) in kernel.signals
    assert result["processes_remaining"] == [600]


def test_settle_drops_record_only_when_objects_are_gone(kernel, tmp_path) -> None:
    journal = kernel.journal(tmp_path / "j", ME)
    journal.record("lab", [NS_A], [])
    kernel.add_namespace(NS_A)
    assert journal.settle("lab") is False
    (kernel.netns / NS_A).unlink()
    assert journal.settle("lab") is True and journal.entries() == []


def test_backend_lab_names_match_generated_patterns() -> None:
    from polmon.backends.hybrid.backend import HybridBackend
    from polmon.topology import parse_topology

    examples = Path(__file__).parents[2] / "examples/topologies"
    l1 = parse_topology((examples / "l1-two-node.yml").read_text(encoding="utf-8"))
    backend = NamespaceBackend(require_linux=False)
    backend.validate(l1)
    namespaces, links = backend.lab_names()
    assert len(namespaces) == 2 and links
    assert set(links) >= set(backend.names.bridges.values())
    pair = NamespaceBackend(require_linux=False, hostless_pair=True)
    pair.validate(l1)
    assert pair.lab_names() == (namespaces, [])

    hybrid_topology = parse_topology((examples / "hybrid-tap.yml").read_text(encoding="utf-8"))
    hybrid = HybridBackend(require_linux=False)
    hybrid.validate(hybrid_topology)
    hybrid_namespaces, hybrid_links = hybrid.lab_names()
    assert hybrid_namespaces and any(name.endswith("t") for name in hybrid_links)
    assert all(NAMESPACE_PATTERN.fullmatch(name) for name in [*namespaces, *hybrid_namespaces])
    assert all(LINK_PATTERN.fullmatch(name) for name in [*links, *hybrid_links])


def test_control_plane_startup_and_reset_reclaim_dead_owner_records(tmp_path) -> None:
    from polmon.api.control import ControlPlane

    directory = tmp_path / "data" / "state" / "lab-ownership"
    # Names that cannot exist on the host: reclamation needs no privileged call.
    LabJournal(directory, owner=DEAD).record("gone", ["polmon00ffff01n"], ["polmon00ffff01b"])
    plane = ControlPlane(tmp_path / "data")
    try:
        assert plane.lab_journal.entries() == []
        assert plane.last_lab_recovery["reason"] == "startup"
        events = [item["event"] for item in plane.logs_query(limit=50)["records"]]
        assert "lab.recovery.reclaimed" in events
        assert plane.resource_status()["lab_recovery"]["reclaimed"][0]["topology_id"] == "gone"

        LabJournal(directory, owner=DEAD).record("later", ["polmon00ffff02n"], [])
        assert plane.reset_all() == {
            "state": "reset",
            "deployments_destroyed": 0,
            "lab_reclaimed": 1,
        }
    finally:
        plane.close()


def test_deploy_refuses_names_journaled_by_another_live_backend(tmp_path) -> None:
    from polmon.api.control import ControlPlane
    from polmon.core.errors import ConfigurationError

    plane = ControlPlane(tmp_path / "data")
    try:
        parent = LabOwner.current()
        parent = LabOwner(os.getppid(), None, parent.boot_id)  # a live process that is not us
        LabJournal(plane.lab_journal.directory, owner=parent).record("lab", [NS_A], [])

        class Backend:
            def lab_names(self):
                return [NS_A], []

        with pytest.raises(ConfigurationError) as raised:
            plane._journal_lab("lab", Backend())
        assert raised.value.message_code == "lab.ownership_conflict"
        assert plane.last_lab_recovery["skipped_live_owner"] == ["lab"]
    finally:
        plane.close()


def test_settle_and_confirm_leave_another_owners_record_alone(kernel, tmp_path) -> None:
    other = kernel.journal(tmp_path / "j", LabOwner(77, 4242, "boot-1"))
    other.record("lab", [NS_A], [])
    mine = kernel.journal(tmp_path / "j", ME)
    mine.confirm("lab")
    assert mine.get("lab")["state"] == "planned"
    assert mine.settle("lab") is False and len(mine.entries()) == 1
