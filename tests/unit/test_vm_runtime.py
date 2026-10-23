"""Жизненный цикл ВМ без гостя: допуск, QMP, команда QEMU, откат и восстановление."""

import os
import socket
import subprocess
import sys
import tempfile
import threading
from collections import namedtuple
from pathlib import Path

import pytest
from polmon_l1_vm import backend as module
from polmon_l1_vm import host, qmp, recovery
from polmon_l1_vm import lab as lab_module
from polmon_l1_vm.backend import VMBackend
from polmon_l1_vm.images import ImageManifest, VMError
from polmon_l1_vm.lab import Lab, file_identity
from polmon_l1_vm.recovery import inspect_run, read_state, recover, write_state

from polmon.backends.namespace.runner import CommandResult
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-vm-addon.yml"
MANIFEST = ImageManifest(
    sha256="0" * 64,
    source_url="https://example.invalid/pinned-test.qcow2",
    distribution="alpine-3.24.1-x86_64-bios-cloudinit",
    license_notice="Test fixture only",
)


# -- допуск -------------------------------------------------------------------------------


def _admit(**overrides):
    values = {
        "count": 2,
        "memory_mb": 256,
        "memory_reserve_mb": 256,
        "directory": Path("/nonexistent/run"),
        "disk_reserve_mb": 512,
        "max_total_disk_mb": 4096,
        "virtual_bytes": 200 * 1024 * 1024,
    }
    return host.admit(**{**values, **overrides})


def test_admission_checks_memory_disk_and_kvm(monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(host, "memory_available_mb", lambda: 2000)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: Usage(0, 0, 10_000 * 1_048_576))
    monkeypatch.setattr(host.os, "access", lambda *args: True)
    result = _admit()
    assert result["requested_memory_mb"] == 640 and result["worst_case_disk_mb"] == 400
    # 640 МБ запроса + запас 256 МБ не помещаются в 800 МБ доступной памяти.
    monkeypatch.setattr(host, "memory_available_mb", lambda: 800)
    with pytest.raises(VMError, match="vm.host_memory"):
        _admit()
    monkeypatch.setattr(host, "memory_available_mb", lambda: None)
    with pytest.raises(VMError, match="vm.host_memory"):
        _admit()
    monkeypatch.setattr(host, "memory_available_mb", lambda: 2000)
    with pytest.raises(VMError, match="vm.disk_limit"):
        _admit(max_total_disk_mb=300)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: Usage(0, 0, 800 * 1_048_576))
    with pytest.raises(VMError, match="vm.host_disk"):
        _admit()
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: Usage(0, 0, 10_000 * 1_048_576))
    monkeypatch.setattr(host.os, "access", lambda *args: False)
    with pytest.raises(VMError, match="vm.kvm_unavailable"):
        _admit()


# -- QMP ----------------------------------------------------------------------------------


class QmpServer:
    """Минимальный сервер QMP; сокет в коротком каталоге из-за предела в 108 байт."""

    def __init__(self, script):
        self.directory = tempfile.mkdtemp(prefix="pmvm-test-")
        self.path = os.path.join(self.directory, "q.sock")
        self.received = []
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(self.path)
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._serve, args=(script,), daemon=True)
        self.thread.start()

    def _serve(self, script):
        connection, _ = self.listener.accept()
        with connection:
            reader = connection.makefile("rb")
            script(connection, reader, self.received)

    def close(self):
        self.thread.join(timeout=3)
        self.listener.close()
        os.unlink(self.path)
        os.rmdir(self.directory)


def test_qmp_sends_negotiation_then_command_and_returns_result():
    def script(connection, reader, received):
        connection.sendall(b'{"QMP": {"version": {}}}\n')
        for reply in (b'{"return": {}}\n', b'{"event": "SHUTDOWN"}\n{"return": {"ok": 1}}\n'):
            received.append(reader.readline())
            connection.sendall(reply)

    server = QmpServer(script)
    try:
        assert qmp.command(server.path, "query-status", timeout=3) == {"ok": 1}
    finally:
        server.close()
    assert server.received == [
        b'{"execute":"qmp_capabilities"}\n',
        b'{"execute": "query-status"}\n',
    ]


def test_qmp_failures_are_bounded_and_coded():
    def flood(connection, reader, received):
        connection.sendall(b"x" * (qmp.MAX_BYTES + 10))

    server = QmpServer(flood)
    try:
        with pytest.raises(VMError, match="vm.qmp_failed"):
            qmp.command(server.path, "quit", timeout=3)
    finally:
        server.close()

    def reject(connection, reader, received):
        connection.sendall(b'{"QMP": {}}\n')
        reader.readline()
        connection.sendall(b'{"error": {"class": "GenericError"}}\n')

    server = QmpServer(reject)
    try:
        with pytest.raises(VMError, match="vm.qmp_failed"):
            qmp.command(server.path, "quit", timeout=3)
    finally:
        server.close()
    with pytest.raises(VMError, match="vm.qmp_failed"):
        qmp.command("/nonexistent/q.sock", "quit")


# -- команда QEMU -------------------------------------------------------------------------


def test_qemu_command_is_kvm_only_isolated_and_per_node(tmp_path):
    topology = load_topology(EXAMPLE)
    vm = VMBackend(base=tmp_path / "base.qcow2", manifest=MANIFEST, directory=tmp_path / "run")
    vm.lab = Lab(topology, vm.runner)
    vm.socket_dir = Path("/tmp/pmvm-x")
    vm.pidfiles = {node.id: tmp_path / f"{node.id}.pid" for node in topology.nodes}
    first, second = (
        vm._command(node, tmp_path / f"{node.id}.qcow2", tmp_path / f"{node.id}-seed.iso")
        for node in topology.nodes
    )
    joined = " ".join(first)
    assert "pc,accel=kvm" in joined and "tcg" not in joined.lower()
    assert "-nodefaults" in first and "-no-user-config" in first and "-no-reboot" in first
    assert "-m 256" in joined and "-smp 1" in joined
    assert "-sandbox" in first and "spawn=deny" in joined
    # Единственная сеть — TAP лаборатории; пользовательской сети (и выхода наружу) нет.
    assert "user," not in joined and "-nic" not in first
    mac = topology.nodes[0].interfaces[0].mac
    assert f"virtio-net-pci,netdev=net0,mac={mac}" in joined
    assert f"ifname={vm.lab.names.taps[('alpha', 'eth0')]}" in joined
    assert f"-uuid {topology.nodes[0].uuid}" in joined
    assert first != second and str(topology.nodes[1].uuid) in " ".join(second)
    assert "format=raw,readonly=on" in joined


# -- откат при ошибке создания ------------------------------------------------------------


class FakeLab:
    instances: list = []

    def __init__(self, topology, runner, mode="userns"):
        self.destroyed = 0
        self.names = Lab(topology, runner).names
        FakeLab.instances.append(self)

    def create(self):
        pass

    def destroy(self):
        self.destroyed += 1

    def resources(self):
        return frozenset()

    def state(self):
        return {"mode": "userns", "namespace": self.names.namespace, "holder": None}


class FailingOverlayRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "qemu-img":
            raise RuntimeError("qemu-img failed")
        return CommandResult("", "", 0)


def test_failed_create_rolls_back_everything(tmp_path, monkeypatch):
    FakeLab.instances.clear()
    monkeypatch.setattr(module, "Lab", FakeLab)
    monkeypatch.setattr(
        module, "verify_image", lambda *a: {"virtual_bytes": 200 * 1024 * 1024, "sha256": "0" * 64}
    )
    monkeypatch.setattr(module, "admit", lambda **kw: {})
    vm = VMBackend(
        base=tmp_path / "base.qcow2",
        manifest=MANIFEST,
        directory=tmp_path / "run",
        runner=FailingOverlayRunner(),
    )
    sockets_before = set(Path(tempfile.gettempdir()).glob("pmvm-*"))
    with pytest.raises(RuntimeError, match="qemu-img failed"):
        vm.create(load_topology(EXAMPLE))
    assert FakeLab.instances[0].destroyed >= 1
    assert list((tmp_path / "run").iterdir()) == []
    assert vm.socket_dir is None and not vm.inspect().resources
    assert set(Path(tempfile.gettempdir()).glob("pmvm-*")) == sockets_before


# -- восстановление -----------------------------------------------------------------------


def _sleeper():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    return process, [process.pid, host.process_start(process.pid)]


def test_recover_stops_recorded_processes_and_removes_only_owned_files(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    outside = tmp_path / "evil"
    outside.write_text("keep")
    (run / "operator.txt").write_text("keep")
    owned = ["alpha.qcow2", "alpha-seed.iso"]
    for name in owned:
        (run / name).write_text("x")
    socket_dir = Path(tempfile.mkdtemp(prefix="pmvm-"))
    process, identity = _sleeper()
    bystander, _ = _sleeper()
    if sys.platform == "win32":
        # Inject procfs identity on Windows while retaining real child termination.
        children = {item.pid: item for item in (process, bystander)}
        monkeypatch.setattr(
            host,
            "process_start",
            lambda pid: "1" if pid in children and children[pid].poll() is None else None,
        )
        monkeypatch.setattr(host, "_zombie", lambda pid: children[pid].poll() is not None)
        identity[1] = "1"
    try:
        write_state(
            run,
            {
                "mode": "userns",
                "owner": _dead_owner(),
                "socket_identity": file_identity(socket_dir),
                "holder": None,
                "files": [*owned, "../evil", "operator.txt"],
                "pidfiles": ["alpha.pid"],
                "socket_dir": str(socket_dir),
                "processes": {"alpha": identity, "stale": [bystander.pid, "0"]},
            },
        )
        assert inspect_run(run)["processes"]["alpha"]["alive"]
        assert sorted(inspect_run(run)["files"]) == sorted(owned)
        result = recover(run)
        process.wait(timeout=5)
        # Запись с чужим временем старта не принадлежит запуску: процесс не тронут.
        assert bystander.poll() is None
    finally:
        for item in (process, bystander):
            item.kill()
            item.wait()
    assert result["recovered"] and result["processes"] == ["alpha"]
    assert sorted(result["files"]) == sorted(owned)
    assert outside.read_text() == "keep" and (run / "operator.txt").read_text() == "keep"
    assert not socket_dir.exists() and read_state(run) is None
    assert recover(run) == {"recovered": False, "processes": [], "released": [], "files": []}
    assert inspect_run(run)["state"] == "absent"


def _dead_owner():
    return {"pid": 2147483647, "start_ticks": 1, "boot_id": recovery.boot_id()}


def test_recover_refuses_foreign_socket_dir_and_bad_state(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    victim = tmp_path / "pmvm-unowned"
    victim.mkdir()
    write_state(
        run,
        {
            "owner": _dead_owner(),
            "mode": "userns",
            "files": [],
            "socket_dir": str(victim),
            "socket_identity": file_identity(victim),
        },
    )
    with pytest.raises(VMError, match="vm.state_invalid"):
        recover(run)
    assert victim.exists()
    (run / "state.json").write_text("{not json")
    with pytest.raises(VMError, match="vm.state_invalid"):
        recover(run)
    write_state(run, {"owner": _dead_owner(), "mode": "netns", "namespace": "eth0", "files": []})
    with pytest.raises(VMError, match="vm.state_invalid"):
        recover(run, runner=None)


def test_recovery_validates_namespace_and_socket_identity_before_mutation(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    owned = run / "alpha.qcow2"
    owned.write_text("keep until ownership is proven")
    calls = []
    monkeypatch.setattr(recovery, "terminate", lambda *a, **kw: calls.append(a))
    monkeypatch.setattr(lab_module, "namespace_identity", lambda _: [1, 200])
    state = {
        "owner": _dead_owner(),
        "mode": "netns",
        "namespace": "polmon12345678n",
        "namespace_identity": [1, 100],
        "files": [owned.name],
        "processes": {"alpha": [123, "1"]},
    }
    write_state(run, state)
    with pytest.raises(VMError, match="vm.state_invalid"):
        recover(run)
    assert not calls and owned.exists() and read_state(run)
    # A missing identity must not authorize deleting a same-named namespace either.
    state.pop("namespace_identity")
    write_state(run, state)
    with pytest.raises(VMError, match="vm.state_invalid"):
        recover(run)
    assert not calls and owned.exists()
    with tempfile.TemporaryDirectory(prefix="pmvm-") as socket_dir:
        state.update(mode="userns", holder=None, socket_dir=socket_dir, socket_identity=[0, 0])
        write_state(run, state)
        with pytest.raises(VMError, match="vm.state_invalid"):
            recover(run)
        assert Path(socket_dir).exists() and not calls and owned.exists()


def test_recovery_refuses_live_owner_and_retains_failed_cleanup(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    write_state(
        run,
        {
            "owner": {"pid": os.getpid(), "start_ticks": 1, "boot_id": recovery.boot_id()},
            "mode": "userns",
        },
    )
    monkeypatch.setattr(recovery.LabOwner, "alive", lambda *a, **kw: True)
    with pytest.raises(VMError, match="vm.lab_exists"):
        recover(run)
    monkeypatch.setattr(recovery.LabOwner, "alive", lambda *a, **kw: False)
    monkeypatch.setattr(lab_module, "_stop_members", lambda *a, **kw: None)
    monkeypatch.setattr(lab_module, "namespace_identity", lambda _: [1, 2])
    write_state(
        run,
        {
            "owner": _dead_owner(),
            "mode": "netns",
            "namespace": "polmon12345678n",
            "namespace_identity": [1, 2],
        },
    )

    class FailedRunner:
        def run(self, *a, **kw):
            raise RuntimeError("deletion failed")

    with pytest.raises(RuntimeError, match="deletion failed"):
        recover(run, FailedRunner())
    assert read_state(run) is not None
    monkeypatch.setattr(host, "process_start", lambda _: None)
    assert not host.alive([123, None])
