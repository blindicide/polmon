"""Real KVM + L0 + nested namespaces on the SAME isolated bridge, not a mock."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from polmon_l1_vm.backend import http_probe_command, readiness
from polmon_l1_vm.host import alive
from polmon_l1_vm.images import ImageManifest, VMError
from polmon_l1_vm.mixed import MixedBackend
from polmon_l1_vm.recovery import recover

from polmon.topology import load_topology

ROOT = Path(__file__).parents[2]
MODES = [
    pytest.param("userns", id="userns"),
    pytest.param("netns", id="netns", marks=pytest.mark.privileged),
]


def host_network():
    return {
        "links": subprocess.run(
            ["ip", "-o", "link"], capture_output=True, text=True, check=True,
        ).stdout,
        "routes": subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, check=True,
        ).stdout,
    }


def wait_for(probe, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := probe():
            return value
        time.sleep(1)
    return probe()


def configured_backend(tmp_path, mode):
    status = readiness()
    if not status["ready"] or not status["modes"].get(mode):
        pytest.skip(f"NOT RUN — environment unavailable: {mode}: {status['missing']}")
    if not status["modes"].get("userns"):
        pytest.skip("NOT RUN — environment unavailable: nested user namespaces required")
    image = os.environ.get("POLMON_VM_TEST_IMAGE")
    manifest = os.environ.get("POLMON_VM_TEST_MANIFEST")
    if not image or not manifest:
        pytest.skip("NOT RUN — environment unavailable: vm.pinned_image_unconfigured")
    return MixedBackend(
        base=Path(image), manifest=ImageManifest.model_validate_json(Path(manifest).read_text()),
        directory=tmp_path / "mixed", vm_nodes=["guest"], mode=mode, peer_report=True,
    )


@pytest.mark.integration
@pytest.mark.parametrize("mode", MODES)
def test_real_mixed_communication_isolation_and_cleanup(tmp_path, mode):
    vm = configured_backend(tmp_path, mode)
    topology = load_topology(ROOT / "examples/topologies/l1-vm-mixed.yml")
    guest, namespace, synthetic = topology.nodes
    before = host_network()
    directory = None
    holders = []
    qemus = []
    ready_at = time.monotonic()
    try:
        vm.create(topology)
        directory = vm.socket_dir
        holders = list(vm.holders.values())
        if vm.lab.holder_identity:
            holders.append(vm.lab.holder_identity)
        vm.start()
        vm.wait_ready()
        qemus = list(vm.identities.values())
        assert len(vm.qemu_pids) == 1
        assert vm.probe_http(str(guest.interfaces[0].ipv4), 8080, guest.id)
        assert vm.probe_http(str(namespace.interfaces[0].ipv4), 8080, namespace.id)
        assert not vm.probe_http(str(namespace.interfaces[0].ipv4), 8080, guest.id)

        # L0 -> VM uses real ARP and ICMP through the exported lab TAP FD.
        assert vm.ping_l1(synthetic.id, str(guest.interfaces[0].ipv4), timeout=5)
        assert vm.ping_l1(synthetic.id, str(namespace.interfaces[0].ipv4), timeout=5)

        # Nested namespace -> VM HTTP/ping, namespace -> L0 ping.
        http = vm.namespace_run(
            namespace.id, http_probe_command(str(guest.interfaces[0].ipv4), 8080),
        )
        assert http.stdout == f"200 POLMON {guest.id} {guest.uuid}\n"
        for target in (guest, synthetic):
            vm.namespace_run(namespace.id, [
                "ping", "-c", "2", "-W", "2", str(target.interfaces[0].ipv4),
            ])

        # Guest-produced reports prove VM -> namespace HTTP and VM -> L0 + namespace ping.
        assert wait_for(lambda: vm.fetch_http(
            str(guest.interfaces[0].ipv4), 8080, "/peers.txt",
        ) == (200, "namespace ok\n")), "VM did not fetch namespace HTTP identity"
        assert wait_for(lambda: vm.fetch_http(
            str(guest.interfaces[0].ipv4), 8080, "/pings.txt",
        ) == (200, "namespace ok\nsynthetic ok\n")), "VM did not ping both real peers"
        assert vm.transport.responders["lab"].answered["icmp_echo"] >= 2

        assert host_network() == before
        assert vm.lab.verify_isolated()
        assert vm.lab.run(["ip", "route", "get", "8.8.8.8"], check=False).returncode != 0
        assert vm.namespace_run(
            namespace.id, ["ip", "route", "get", "8.8.8.8"], check=False,
        ).returncode != 0
        for node in (guest, namespace):
            with socket.socket() as probe:
                probe.settimeout(1)
                with pytest.raises(OSError):
                    probe.connect((str(node.interfaces[0].ipv4), 8080))
        print("REAL-VM-EVIDENCE " + json.dumps({
            "case": "mixed", "mode": mode,
            "ready_seconds": round(time.monotonic() - ready_at, 2),
            "sample": vm.sample(), "integration_verified": False,
        }, default=list))
    except BaseException:
        for log in vm.directory.glob("*.log"):
            print(f"--- {log.name}\n{log.read_text(errors='replace')[-6000:]}")
        raise
    finally:
        vm.destroy()

    assert not vm.resources()
    assert not vm.http_servers and not vm.transport.responders
    assert not vm.transport.taps
    assert not any(alive(identity) for identity in [*holders, *qemus])
    assert not list(vm.directory.iterdir())
    assert directory is not None and not directory.exists()
    assert host_network() == before
    vm.destroy()  # Idempotence is part of deterministic cleanup.


@pytest.mark.integration
@pytest.mark.parametrize("mode", MODES)
def test_real_mixed_partial_namespace_creation_rolls_back(tmp_path, mode, monkeypatch):
    vm = configured_backend(tmp_path, mode)
    topology = load_topology(ROOT / "examples/topologies/l1-vm-mixed.yml")
    before = host_network()
    create_namespace = vm._create_namespace
    identities = []
    socket_directory = []

    def fail_after_namespace(node):
        create_namespace(node)
        identities.extend(vm.holders.values())
        if vm.lab.holder_identity:
            identities.append(vm.lab.holder_identity)
        socket_directory.append(vm.socket_dir)
        raise VMError("vm.mixed_start_failed")

    monkeypatch.setattr(vm, "_create_namespace", fail_after_namespace)
    try:
        with pytest.raises(VMError, match="vm.mixed_start_failed"):
            vm.create(topology)
        assert not vm.resources()
        assert not any(alive(identity) for identity in identities)
        assert not vm.transport.taps
        assert not list(vm.directory.iterdir())
        assert socket_directory and not socket_directory[0].exists()
        assert host_network() == before
    finally:
        vm.destroy()


@pytest.mark.integration
@pytest.mark.parametrize("mode", MODES)
def test_mixed_nested_namespace_journal_survives_owner_crash_before_vm_start(tmp_path, mode):
    """Exercise nested ownership recovery, not an additional guest-crash claim."""
    vm = configured_backend(tmp_path, mode)
    before = host_network()
    source = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from polmon.topology import load_topology
from polmon_l1_vm.images import ImageManifest
from polmon_l1_vm.mixed import MixedBackend
vm = MixedBackend(base=Path(sys.argv[2]), manifest=ImageManifest.model_validate_json(sys.argv[3]),
                  directory=Path(sys.argv[4]), vm_nodes=['guest'], mode=sys.argv[5])
vm.create(load_topology(sys.argv[6]))
print(json.dumps({'holders': list(vm.holders.values()), 'lab_holder': vm.lab.holder_identity,
                  'socket': str(vm.socket_dir)}), flush=True)
os._exit(77)
"""
    try:
        child = subprocess.run([
            sys.executable, "-c", source, str(ROOT / "addons/l1-vm/src"),
            str(vm.base), vm.manifest.model_dump_json(), str(vm.directory), mode,
            str(ROOT / "examples/topologies/l1-vm-mixed.yml"),
        ], capture_output=True, text=True, timeout=30, check=False)
        assert child.returncode == 77, child.stderr
        owned = json.loads(child.stdout)
        identities = owned["holders"]
        if owned["lab_holder"]:
            identities.append(owned["lab_holder"])
        assert all(alive(identity) for identity in identities)
        assert recover(vm.directory)["recovered"] is True
        assert not any(alive(identity) for identity in identities)
        assert not Path(owned["socket"]).exists()
        assert not list(vm.directory.iterdir())
        assert host_network() == before
    finally:
        recover(vm.directory)
