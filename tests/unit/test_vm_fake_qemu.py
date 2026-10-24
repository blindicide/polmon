"""Жизненный цикл ВМ против подставного QEMU: запуск, остановка по QMP, откат и очистка."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from polmon_l1_vm import backend as module
from polmon_l1_vm.backend import VMBackend
from polmon_l1_vm.images import ImageManifest, VMError
from polmon_l1_vm.lab import Lab

from polmon.topology import load_topology

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix-сокеты QMP и /proc")

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_qemu.py"
EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-vm-addon.yml"
MANIFEST = ImageManifest(
    sha256="0" * 64,
    source_url="https://example.invalid/pinned-test.qcow2",
    distribution="alpine-3.24.1-x86_64-bios-cloudinit",
    license_notice="Test fixture only",
)


class ProcessLab:
    """Лаборатория без сетевых пространств: гость — обычный дочерний процесс."""

    def __init__(self, topology, runner, mode="userns"):
        self.names = Lab(topology, runner).names
        self.runner = runner
        self.on_created = lambda: None

    def create(self):
        pass

    def destroy(self):
        pass

    def resources(self):
        return frozenset()

    def state(self):
        return {"mode": "userns", "namespace": self.names.namespace, "holder": None}

    overrides: dict[str, str] = {}

    def start(self, argv, *, log_path, max_output_bytes=262_144):
        assert argv[0] == "qemu-system-x86_64"
        mode = self.overrides.get(argv[argv.index("-name") + 1])
        env = {**os.environ, **({"POLMON_FAKE_QEMU": mode} if mode else {})}
        with log_path.open("ab") as log:
            return subprocess.Popen(
                [sys.executable, str(FAKE), *argv[1:]],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )


class FileRunner:
    """qemu-img не нужен: перекрытия и образы начальной конфигурации — пустые файлы."""

    def __init__(self):
        from polmon.backends.namespace.runner import CommandRunner

        self._real = CommandRunner()

    def run(self, argv, **kwargs):
        return self._real.run([sys.executable, "-c", "pass"], **kwargs)

    def start(self, *args, **kwargs):
        return self._real.start(*args, **kwargs)


@pytest.fixture
def vm(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "Lab", ProcessLab)
    monkeypatch.setattr(
        module, "verify_image", lambda *a: {"virtual_bytes": 200 * 1024 * 1024, "sha256": "0" * 64}
    )
    monkeypatch.setattr(module, "admit", lambda **kw: {})

    def seed(directory, node, *args, **kwargs):
        path = directory / f"{node.id}-seed.iso"
        path.write_bytes(b"seed")
        return path

    monkeypatch.setattr(module, "create_seed", seed)
    backend = VMBackend(
        base=tmp_path / "base.qcow2",
        manifest=MANIFEST,
        directory=tmp_path / "run",
        runner=FileRunner(),
    )
    sockets_before = set(Path(tempfile.gettempdir()).glob("pmvm-*"))
    (tmp_path / "base.qcow2").write_bytes(b"verified base")
    backend.create(load_topology(EXAMPLE))
    yield backend
    backend.destroy()
    assert set(Path(tempfile.gettempdir()).glob("pmvm-*")) == sockets_before


def test_start_stop_and_destroy_leave_nothing_behind(vm, tmp_path):
    vm.start()
    pids = vm.qemu_pids
    assert len(pids) == 2 and len(set(pids)) == 2
    assert {item.name for item in (tmp_path / "run").glob("*.pid")} == {"alpha.pid", "bravo.pid"}
    vm.stop()
    assert vm.qemu_pids == [] and vm.phase == "stopped"
    vm.destroy()
    leftovers = {path.name for path in (tmp_path / "run").iterdir()}
    assert leftovers == set() and vm.socket_dir is None and not vm.inspect().resources


@pytest.mark.parametrize("mode", ["ignore-quit", "ignore-term"])
def test_stop_escalates_when_the_guest_ignores_quit_or_term(vm, mode):
    ProcessLab.overrides = {"alpha": mode, "bravo": mode}
    try:
        vm.start()
        assert len(vm.qemu_pids) == 2
        vm.stop()
    finally:
        ProcessLab.overrides = {}
    assert vm.qemu_pids == []


def test_failed_launch_reports_a_code_and_stops_earlier_guests(vm):
    # Первый гость запускается, второй отвергает командную строку: первый не должен остаться.
    ProcessLab.overrides = {"bravo": "bad-args"}
    try:
        with pytest.raises(VMError, match="vm.qemu_exited"):
            vm.start()
    finally:
        ProcessLab.overrides = {}
    assert vm.qemu_pids == [] and vm.phase == "created"
    assert "simulated rejection" in (vm.directory / "bravo-qemu.log").read_text()


def test_stop_attempts_every_guest_before_reporting_a_cleanup_failure(vm, monkeypatch):
    vm.start()
    first, second = list(vm.identities.values())
    real = module.terminate
    monkeypatch.setattr(
        module,
        "terminate",
        lambda identity, grace=3: False if identity == first else real(identity),
    )
    with pytest.raises(VMError, match="vm.cleanup_failed"):
        vm.stop()
    # Второй гость остановлен, несмотря на отказ первого; первый остаётся записанным.
    assert not module.alive(second) and vm.phase == "started"
    monkeypatch.setattr(module, "terminate", real)
    vm.stop()


def test_start_refuses_a_base_image_replaced_after_verification(vm):
    vm.base.write_bytes(b"swapped after hashing")
    with pytest.raises(VMError, match="vm.image_changed"):
        vm.start()
    assert vm.qemu_pids == [] and vm.phase == "created"


def test_socket_directory_with_a_comma_is_refused_before_anything_is_created(tmp_path, monkeypatch):
    comma = tmp_path / "a,b"
    comma.mkdir()
    make = tempfile.mkdtemp  # тот же модуль: подмену нужно вызывать через исходную функцию
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: make(prefix=prefix, dir=comma))
    monkeypatch.setattr(module, "Lab", ProcessLab)
    monkeypatch.setattr(module, "verify_image", lambda *a: {"virtual_bytes": 1 << 20})
    monkeypatch.setattr(module, "admit", lambda **kw: {})
    backend = VMBackend(
        base=tmp_path / "base.qcow2",
        manifest=MANIFEST,
        directory=tmp_path / "run",
        runner=FileRunner(),
    )
    (tmp_path / "base.qcow2").write_bytes(b"x")
    with pytest.raises(VMError, match="vm.path_invalid"):
        backend.create(load_topology(EXAMPLE))
    assert list(comma.iterdir()) == [] and list((tmp_path / "run").iterdir()) == []
