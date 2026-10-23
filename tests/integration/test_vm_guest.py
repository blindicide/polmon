"""Explicit real VM gate. A skip is NOT a successful VM integration run."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from polmon_l1_vm.backend import VMBackend, readiness
from polmon_l1_vm.images import ImageManifest

from polmon.topology import load_topology


@pytest.mark.privileged
@pytest.mark.integration
def test_real_vm_boot_http_clones_and_teardown(tmp_path):
    status = readiness()
    if not status["ready"]:
        pytest.skip("NOT RUN — environment unavailable: " + ",".join(status["missing"]))
    image_name = os.environ.get("POLMON_VM_TEST_IMAGE")
    manifest_name = os.environ.get("POLMON_VM_TEST_MANIFEST")
    if not image_name or not manifest_name:
        pytest.skip("NOT RUN — environment unavailable: vm.pinned_image_unconfigured")
    base = Path(image_name)
    manifest = ImageManifest.model_validate_json(Path(manifest_name).read_text())
    topology = load_topology(Path(__file__).parents[2] / "examples/topologies/l1-vm-addon.yml")
    vm = VMBackend(base=base, manifest=manifest, directory=tmp_path / "vm-run")
    try:
        vm.create(topology)
        vm.start()
        vm.wait_ready()
        assert len(vm.qemu_pids) == 2
        # Each clone wrote its own unique identity into its private guest filesystem.
        for node in topology.nodes:
            assert vm.probe_http(str(node.interfaces[0].ipv4), 8080, node.id)
        assert hashlib.sha256(base.read_bytes()).hexdigest() == manifest.sha256
        print("REAL-VM-EVIDENCE " + json.dumps(vm.sample(), default=list))
    finally:
        vm.destroy()
    assert not vm.inspect().resources
    assert not list(vm.directory.glob("*.qcow2"))
