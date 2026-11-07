"""Fault injection against real KVM guests, not substitutes backed by fake QEMU."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from polmon_l1_vm.backend import VMBackend, VMLimits, readiness
from polmon_l1_vm.host import alive
from polmon_l1_vm.images import ImageManifest, VMError
from polmon_l1_vm.lab import namespace_identity
from polmon_l1_vm.recovery import read_state

from polmon.api.vm import VMJobs, VMRequest, addon_environment
from polmon.topology import load_topology
from tests.integration.test_vm_guest import MODES, TOPOLOGY, host_links


def wait_for(check, *, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"condition did not become true within {timeout} seconds")


@pytest.fixture(params=MODES)
def guest_environment(request):
    mode = request.param
    status = readiness()
    if not status["ready"] or not status["modes"].get(mode):
        pytest.skip(f"NOT RUN — environment unavailable: {mode}: {status['missing']}")
    image = os.environ.get("POLMON_VM_TEST_IMAGE")
    manifest = os.environ.get("POLMON_VM_TEST_MANIFEST")
    if not image or not manifest:
        pytest.skip("NOT RUN — environment unavailable: vm.pinned_image_unconfigured")
    topology = load_topology(TOPOLOGY)
    topology.id = "vm-faults"
    pinned = ImageManifest.model_validate_json(Path(manifest).read_text())
    return mode, Path(image), pinned, topology


def ready_state(path):
    state = read_state(path)
    return state if state and state.get("ready") else None


def assert_clean(directory, state, links_before):
    assert not (directory / "state.json").exists()
    if directory.exists():
        assert list(directory.iterdir()) == []
    assert not Path(state["socket_dir"]).exists()
    assert not any(alive(identity) for identity in state["processes"].values())
    if state.get("holder"):
        assert not alive(state["holder"])
    if state["mode"] == "netns":
        assert namespace_identity(state["namespace"]) is None
    assert host_links() == links_before


def record(mode, case):
    print("REAL-VM-EVIDENCE " + json.dumps({"mode": mode, "case": case, "cleanup": True}))


@pytest.mark.integration
def test_real_guest_crash_is_detected_and_survivor_is_cleaned(tmp_path, guest_environment):
    mode, image, manifest, topology = guest_environment
    before = host_links()
    vm = VMBackend(base=image, manifest=manifest, directory=tmp_path / "run", mode=mode)
    try:
        vm.create(topology)
        vm.start()
        vm.wait_ready()
        state = read_state(vm.directory)
        crashed = vm.identities[topology.nodes[0].id]
        os.kill(crashed[0], signal.SIGKILL)
        wait_for(lambda: not alive(crashed), timeout=10)
        with pytest.raises(VMError, match="vm.qemu_exited"):
            vm.wait_ready()
    finally:
        vm.destroy()
    assert_clean(vm.directory, state, before)
    record(mode, "guest_crash")


@pytest.mark.integration
def test_real_guest_readiness_timeout_cleans_up(tmp_path, guest_environment, monkeypatch):
    mode, image, manifest, topology = guest_environment
    topology.nodes = topology.nodes[:1]
    before = host_links()
    vm = VMBackend(
        base=image, manifest=manifest, directory=tmp_path / "run", mode=mode,
        limits=VMLimits(boot_timeout_seconds=10),
    )
    try:
        vm.create(topology)
        vm.start()
        state = read_state(vm.directory)
        # Deliberate probe outage while an actual KVM guest is alive.
        monkeypatch.setattr(vm, "fetch_http", lambda *args: None)
        with pytest.raises(VMError, match="vm.boot_timeout"):
            vm.wait_ready()
        assert vm.qemu_pids
    finally:
        vm.destroy()
    assert_clean(vm.directory, state, before)
    record(mode, "readiness_timeout")


@pytest.mark.integration
def test_real_partial_launch_failure_stops_already_started_guest(
    tmp_path, guest_environment, monkeypatch
):
    mode, image, manifest, topology = guest_environment
    before = host_links()
    vm = VMBackend(base=image, manifest=manifest, directory=tmp_path / "run", mode=mode)
    original = vm._command

    def fail_second(node, overlay, seed):
        if node.id == topology.nodes[1].id:
            return ["qemu-system-x86_64", "-polmon-deliberate-invalid-option"]
        return original(node, overlay, seed)

    monkeypatch.setattr(vm, "_command", fail_second)
    try:
        vm.create(topology)
        with pytest.raises(VMError, match="vm.qemu_exited"):
            vm.start()
        state = read_state(vm.directory)
        assert topology.nodes[0].id in vm.identities
        assert not vm.qemu_pids
    finally:
        vm.destroy()
    assert_clean(vm.directory, state, before)
    record(mode, "partial_launch_failure")


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["cancel", "timeout", "owner_crash"])
def test_real_api_job_faults_reclaim_guests(tmp_path, guest_environment, fault):
    mode, image, _, topology = guest_environment
    topology.nodes = topology.nodes[:1]
    before = host_links()
    jobs = VMJobs(tmp_path / "jobs", bundled=lambda: image)
    try:
        started = jobs.start(VMRequest(
            action="run", mode=mode, topology=topology, hold_seconds=600,
        ))
        job = jobs._jobs[started["job_id"]]
        state = wait_for(lambda: ready_state(job.directory))
        assert all(alive(identity) for identity in state["processes"].values())
        if fault == "cancel":
            jobs.cancel(job.job_id)
        elif fault == "timeout":
            jobs._expire(job)
        else:
            job.process.kill()  # no finally block: supervisor must use the ownership journal
        done = wait_for(lambda: jobs.job(job.job_id) if job.state != "running" else None)
        assert done["state"] == ("cancelled" if fault == "cancel" else "failed")
        if fault == "timeout":
            assert done["message_code"] == "vm.timeout"
        if fault == "owner_crash":
            assert done["exit_code"] == -signal.SIGKILL
        assert not (done["message_params"] or {}).get("left_behind")
    finally:
        jobs.shutdown(timeout=60)
    assert_clean(job.directory, state, before)
    assert list((jobs.directory / "runs").iterdir()) == []
    record(mode, fault)


BACKEND_DRIVER = """
import json, sys, time
from pathlib import Path
from polmon.api.vm import VMJobs, VMRequest
from polmon.topology.models import Topology
directory, image, mode, topology = sys.argv[1:]
jobs = VMJobs(Path(directory), bundled=lambda: Path(image))
job = jobs.start(VMRequest(action='run', mode=mode, hold_seconds=600,
                          topology=Topology.model_validate_json(topology)))
(Path(directory) / 'driver-job.json').write_text(json.dumps(job))
time.sleep(600)
"""


@pytest.mark.integration
def test_real_backend_death_stops_owned_job_and_successor_recovers(tmp_path, guest_environment):
    mode, image, _, topology = guest_environment
    topology.nodes = topology.nodes[:1]
    directory = tmp_path / "jobs"
    before = host_links()
    backend = subprocess.Popen(
        [sys.executable, "-c", BACKEND_DRIVER, str(directory), str(image), mode,
         topology.model_dump_json(by_alias=True)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=addon_environment(),
    )
    state = None
    try:
        marker = directory / "driver-job.json"
        wait_for(marker.exists, timeout=30)
        job = json.loads(marker.read_text())
        run = directory / "runs" / job["job_id"]
        state = wait_for(lambda: ready_state(run))
        backend.kill()
        backend.communicate(timeout=10)
        # The CLI's identity-pinned parent guard must clean up despite a broken stderr pipe.
        wait_for(lambda: not (run / "state.json").exists(), timeout=60)
        successor = VMJobs(directory, bundled=lambda: image)
        assert successor.recover() == {"directories": 1, "recovered": 1, "failed": 0}
        assert_clean(run, state, before)
    finally:
        if backend.poll() is None:
            backend.kill()
            backend.communicate(timeout=10)
        if state:
            # Always attempt owned recovery even when an assertion above fails.
            wait_for(lambda: not alive([
                state["owner"]["pid"], str(state["owner"]["start_ticks"])
            ]), timeout=60)
            VMJobs(directory, bundled=lambda: image).recover()
    record(mode, "backend_crash_and_startup_recovery")
