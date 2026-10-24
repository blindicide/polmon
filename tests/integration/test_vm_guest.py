"""Настоящие гости KVM. Пропуск теста НЕ считается успешным прогоном ВМ."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from polmon_l1_vm.backend import VMBackend, readiness
from polmon_l1_vm.images import ImageManifest

from polmon.backends.namespace.runner import CommandRunner
from polmon.topology import load_topology

TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/l1-vm-addon.yml"
MODES = [
    pytest.param("userns", id="userns"),
    pytest.param("netns", id="netns", marks=pytest.mark.privileged),
]


def host_links() -> str:
    return subprocess.run(["ip", "-o", "link"], capture_output=True, text=True, check=True).stdout


def wait_for(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    return check()


def diagnose(vm, topology) -> None:
    """Состояние лабораторной сети и сырой результат опроса: что видит хост, а что гость."""
    if vm.lab is None:
        return
    probes = [["ip", "-o", "addr"], ["ip", "neigh"], ["ip", "-s", "-o", "link"]]
    for node in topology.nodes:
        address = str(node.interfaces[0].ipv4)
        probes.append(["ping", "-c", "1", "-W", "1", address])
        probes.append(
            [sys.executable, "-m", "polmon_l1_vm.cli", "probe-http", address, "8080", "/"]
        )
    for command in probes:
        try:
            result = vm.lab.run(command, as_owner=True, check=False, timeout=15)
            print(f"--- {' '.join(command)} -> rc={result.returncode}")
            print((result.stdout + result.stderr)[-1500:])
        except Exception as error:  # noqa: BLE001 - диагностика не должна скрывать исходный отказ
            print(f"--- {' '.join(command)} -> {type(error).__name__}: {error}")


@pytest.mark.integration
@pytest.mark.parametrize("mode", MODES)
def test_real_two_guest_lifecycle_identity_isolation_and_cleanup(tmp_path, mode):
    status = readiness()
    if not status["modes"].get(mode):
        pytest.skip(f"NOT RUN — environment unavailable: mode {mode} ({status['missing']})")
    if status["missing"] and not any(status["modes"].values()):
        pytest.skip("NOT RUN — environment unavailable: " + ",".join(status["missing"]))
    image_name = os.environ.get("POLMON_VM_TEST_IMAGE")
    manifest_name = os.environ.get("POLMON_VM_TEST_MANIFEST")
    if not image_name or not manifest_name:
        pytest.skip("NOT RUN — environment unavailable: vm.pinned_image_unconfigured")
    base = Path(image_name)
    manifest = ImageManifest.model_validate_json(Path(manifest_name).read_text())
    topology = load_topology(TOPOLOGY)
    alpha, bravo = topology.nodes
    runner = CommandRunner()
    links_before = host_links()
    vm = VMBackend(
        base=base,
        manifest=manifest,
        directory=tmp_path / "vm-run",
        mode=mode,
        peer_report=True,
    )
    socket_dir = None
    holder = None
    try:
        vm.create(topology)
        socket_dir, holder = vm.socket_dir, vm.lab.holder_identity
        initial = {
            n.id: (vm.directory / f"{n.id}.qcow2").stat().st_blocks * 512 for n in (alpha, bravo)
        }
        vm.start()
        vm.wait_ready()
        assert len(vm.qemu_pids) == 2 and len(set(vm.qemu_pids)) == 2

        # Идентичность: каждый клон отдаёт собственные имя и uuid, чужую подмену проба отвергает.
        addresses = {n.id: str(n.interfaces[0].ipv4) for n in (alpha, bravo)}
        for node in (alpha, bravo):
            assert vm.probe_http(addresses[node.id], 8080, node.id)
        assert not vm.probe_http(addresses["alpha"], 8080, "bravo")
        assert not vm.probe_http(addresses["bravo"], 8080, "alpha")

        # Трафик гость-гость: каждый гость сам запросил страницу соседа и опубликовал итог.
        def peers_ok():
            reports = {n: vm.fetch_http(addresses[n], 8080, "/peers.txt") for n in addresses}
            expected = {"alpha": "bravo ok\n", "bravo": "alpha ok\n"}
            return all(reports[n] == (200, expected[n]) for n in expected) or None

        assert wait_for(peers_ok), "guests did not reach each other over the lab bridge"

        # Изоляция: из пространства хоста гостей не видно, в лаборатории нет маршрута наружу.
        assert host_links() == links_before
        for address in addresses.values():
            probe = socket.socket()
            probe.settimeout(2)
            with pytest.raises(OSError):
                probe.connect((address, 8080))
            probe.close()
        assert vm.lab.verify_isolated()["namespace"] == vm.lab.names.namespace
        assert vm.lab.run(["ip", "route", "get", "8.8.8.8"], check=False).returncode != 0

        sample = vm.sample()
        for node in (alpha, bravo):
            entry = sample["nodes"][node.id]
            assert entry["rss_bytes"] and entry["cpu_seconds"] > 0
            assert entry["interfaces"]["eth0"]["rx_packets"] > 0
            assert entry["overlay_allocated_bytes"] > initial[node.id]
        print("REAL-VM-EVIDENCE " + json.dumps({"mode": mode, "sample": sample}, default=list))

        # Запись гостя остаётся в его собственном перекрытии; базовый образ не тронут.
        vm.stop()
        assert not vm.qemu_pids
        overlays = [vm.directory / f"{n.id}.qcow2" for n in (alpha, bravo)]
        differs = runner.run(
            ["qemu-img", "compare", "-f", "qcow2", "-F", "qcow2", *map(str, overlays)],
            check=False,
            timeout=60,
        )
        assert differs.returncode == 1, differs.stdout
        for overlay in overlays:
            same = runner.run(
                ["qemu-img", "compare", "-f", "qcow2", "-F", "qcow2", str(base), str(overlay)],
                check=False,
                timeout=60,
            )
            assert same.returncode == 1, same.stdout
        assert hashlib.sha256(base.read_bytes()).hexdigest() == manifest.sha256
    except BaseException:
        # Консоль гостя исчезнет вместе с запуском: сохраняем её в выводе до очистки.
        for log in sorted(vm.directory.glob("*-qemu.log")):
            print(f"--- {log.name} (tail) ---\n{log.read_text(errors='replace')[-6000:]}")
        diagnose(vm, topology)
        raise
    finally:
        vm.destroy()

    # Ничего не осталось: ресурсы, файлы запуска, сокеты, держатель пространства, устройства хоста.
    assert not vm.inspect().resources
    leftovers = [p.name for p in vm.directory.iterdir() if p.suffix in {".qcow2", ".iso", ".pid"}]
    assert not leftovers and not (vm.directory / "state.json").exists()
    assert socket_dir is not None and not socket_dir.exists()
    if holder is not None:
        assert not Path(f"/proc/{holder[0]}").exists()
    assert host_links() == links_before
