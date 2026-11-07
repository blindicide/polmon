"""Opt-in selection, isolated link planning and ownership-before-unshare regressions."""

import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from polmon_l1_vm import backend as vm_module
from polmon_l1_vm import mixed
from polmon_l1_vm.backend import VMBackend, VMLimits
from polmon_l1_vm.images import ImageManifest, VMError
from polmon_l1_vm.mixed import MixedBackend
from polmon_l1_vm.seed import seed_documents

from polmon.backends.namespace.runner import CommandResult
from polmon.topology import load_topology
from polmon.topology.models import Node, Topology

ROOT = Path(__file__).parents[2]


@pytest.fixture
def topology():
    return load_topology(ROOT / "examples/topologies/l1-vm-mixed.yml")


@pytest.fixture
def backend(tmp_path):
    manifest = ImageManifest.model_validate_json(
        (ROOT / "examples/vm/alpine-3.24.1-manifest.json").read_text()
    )
    return MixedBackend(
        base=tmp_path / "base.qcow2", directory=tmp_path / "run", manifest=manifest,
        vm_nodes=["guest"],
    )


def changed(topology, update):
    data = topology.model_dump(mode="json", by_alias=True)
    update(data)
    return Topology.model_validate(data)


def test_selection_is_explicit_and_counts_only_vm_admission(backend, topology):
    backend.limits = VMLimits(max_vms=1, max_vcpus=1)
    plan = backend.plan(topology)
    assert plan["vm_nodes"] == ["guest"]
    assert plan["namespace_nodes"] == ["namespace"]
    assert plan["l0_nodes"] == ["synthetic"]
    assert [node["id"] for node in plan["nodes"]] == ["guest"]
    assert plan["estimated_memory_mb"] == 320
    assert plan["integration_verified"] is False
    assert backend._seed_topology(backend.vm_topology) is topology
    # The ordinary backend still refuses mixed nodes; L1 did not acquire new meaning.
    with pytest.raises(VMError):
        VMBackend.validate(backend, topology)


@pytest.mark.parametrize("selection", [[], ["guest", "guest"], ["absent"], ["synthetic"]])
def test_invalid_selection_rejected_before_any_resources(backend, topology, selection):
    with pytest.raises(VMError, match="vm.mixed_unsupported"):
        candidate = MixedBackend(
            base=backend.base, directory=backend.directory, manifest=backend.manifest,
            vm_nodes=selection,
        )
        candidate.validate(topology)
    assert not backend.directory.exists()


@pytest.mark.parametrize("drop", ["namespace", "synthetic"])
def test_vm_plus_only_one_peer_kind_is_supported(backend, topology, drop):
    topology = changed(topology, lambda data: data.update(
        nodes=[node for node in data["nodes"] if node["id"] != drop]
    ))
    backend.validate(topology)
    assert backend.vm_topology.nodes[0].id == "guest"


@pytest.mark.parametrize("kind", [
    "l2", "empty", "long-interface", "loopback", "service", "resources",
])
def test_unsupported_peer_shapes_rejected(backend, topology, kind):
    def update(data):
        node = data["nodes"][1]
        if kind == "l2":
            node["class"] = "l2"
        elif kind == "empty":
            node["interfaces"] = []
        elif kind == "long-interface":
            node["interfaces"][0]["id"] = "interface-too-long"
        elif kind == "loopback":
            node["interfaces"][0]["id"] = "lo"
        elif kind == "service":
            node["services"][0]["implementation"] = "ssh"
        else:
            node["resources"] = {"memory_mb": 32, "cpu_millicores": 50}
    with pytest.raises(VMError):
        backend.validate(changed(topology, update))
    assert not backend.directory.exists()


def test_l0_cannot_silently_lose_additional_interfaces(backend, topology):
    def update(data):
        data["networks"].append({"id": "other", "ipv4_subnet": "192.168.238.0/24"})
        data["nodes"][2]["interfaces"].append({
            "id": "eth1", "network": "other", "mac": "02:50:4f:07:02:03",
            "ipv4": "192.168.238.13",
        })
    with pytest.raises(VMError, match="vm.mixed_unsupported"):
        backend.validate(changed(topology, update))


@pytest.mark.parametrize("node_class,limit", [("l0", mixed.MAX_L0), ("l1", mixed.MAX_NAMESPACES)])
def test_peer_counts_are_bounded(backend, topology, node_class, limit):
    nodes = [topology.nodes[0]]
    for index in range(limit + 1):
        nodes.append(Node.model_validate({
            "id": f"peer-{index}", "class": node_class,
            "interfaces": [{
                "id": "eth0", "network": "lab", "mac": f"02:50:4f:09:00:{index:02x}",
                "ipv4": f"192.168.239.{index + 20}",
            }],
        }))
    with pytest.raises(VMError, match="vm.mixed_unsupported"):
        backend.validate(mixed.subset(topology, nodes))


@pytest.mark.parametrize("mode", ["userns", "netns"])
def test_all_peers_share_owned_lab_bridges_and_probe_reservations(backend, topology, mode):
    topology = changed(topology, lambda data: data["nodes"][2]["interfaces"][0].update(
        ipv4="192.168.239.254"
    ))
    backend.mode = mode
    backend.validate(topology)
    lab = backend._make_lab(backend.vm_topology)
    assert str(lab.names.probes["lab"]) == "192.168.239.253/24"
    assert set(lab.names.taps) == {("guest", "eth0")}
    lines = lab._lines()
    assert sum("type bridge" in line for line in lines) == 1
    assert sum("tuntap add" in line for line in lines) == 2
    assert all(lab.names.bridges["lab"] in line for line in lines if " master " in line)
    assert not any("default" in line or "nat" in line for line in lines)
    assert len(lab.veths) == 1
    assert not backend.directory.exists()


def test_generated_link_collisions_fail_before_creation(backend, topology, monkeypatch):
    monkeypatch.setattr(mixed, "_name", lambda *_: "polmon00000000t")
    with pytest.raises(VMError, match="vm.mixed_unsupported"):
        backend.validate(topology)


@pytest.mark.parametrize("field", ["ipv4", "mac"])
def test_vm_namespace_identity_collisions_rejected_by_shared_topology(topology, field):
    with pytest.raises(ValueError):
        changed(topology, lambda data: data["nodes"][1]["interfaces"][0].update({
            field: data["nodes"][0]["interfaces"][0][field],
        }))


def test_foreign_link_is_still_rejected(backend, topology):
    backend.validate(topology)
    lab = backend._make_lab(backend.vm_topology)
    lab.run = Mock(return_value=CommandResult("1: uplink: <UP>\n", "", 0))
    with pytest.raises(VMError, match="vm.lab_foreign_link"):
        lab.verify_isolated()


def test_holder_identity_journaled_before_go_and_child_before_veth(backend, topology, monkeypatch):
    backend.validate(topology)
    backend.directory.mkdir()
    lab = backend._make_lab(backend.vm_topology)
    backend.lab = lab
    lab.namespace_identity = [1, 2]
    lab.holder = SimpleNamespace(pid=101)
    pidfile = backend.directory / "namespace.pid"
    go = backend.directory / "namespace-go"
    snapshots = []
    backend._journal = lambda: snapshots.append({
        "go": go.exists(), "processes": dict(backend.auxiliary_processes),
        "children": list(backend.child_namespaces), "files": set(backend.auxiliary_files),
    })

    def launch(*_, **__):
        pidfile.write_text("12345")
        (backend.directory / "namespace-ready").touch()
        return SimpleNamespace(poll=lambda: None)

    backend.runner.start = launch
    lab.run = Mock()
    backend.namespace_run = Mock()
    monkeypatch.setattr(mixed, "process_start", lambda _: "456")
    monkeypatch.setattr(mixed, "file_identity", lambda _: [3, 4])
    backend._create_namespace(topology.nodes[1])
    assert snapshots[0]["processes"] == {}
    assert snapshots[1]["processes"] == {"namespace": (12345, "456")}
    assert snapshots[1]["go"] is False
    assert snapshots[2]["go"] is True
    assert snapshots[2]["children"] == [
        {"holder": [12345, "456"], "namespace_identity": [3, 4]},
    ]
    assert snapshots[0]["files"] == {
        backend.directory / "namespace-go", backend.directory / "namespace-ready",
    }
    assert lab.run.call_args_list[0].args[0][:3] == ["ip", "link", "add"]


def test_holder_helper_requires_ack_before_unshare(tmp_path, monkeypatch):
    pidfile, go, ready = (tmp_path / name for name in ("peer.pid", "peer-go", "peer-ready"))
    monkeypatch.setattr(mixed, "HELPER_TIMEOUT", 0)
    execvp = Mock()
    monkeypatch.setattr(mixed.os, "execvp", execvp)
    assert mixed.helper_main(["holder", str(pidfile), str(go), str(ready)]) == 2
    assert pidfile.read_text() == str(os.getpid())
    execvp.assert_not_called()
    assert not ready.exists()


def test_holder_exec_uses_frozen_dispatch_without_forking(tmp_path, monkeypatch):
    pidfile, go, ready = (tmp_path / name for name in ("peer.pid", "peer-go", "peer-ready"))
    go.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/bundle/polmon")
    execvp = Mock(side_effect=RuntimeError("exec captured"))
    monkeypatch.setattr(mixed.os, "execvp", execvp)
    with pytest.raises(RuntimeError, match="exec captured"):
        mixed.helper_main(["holder", str(pidfile), str(go), str(ready)])
    assert pidfile.read_text() == str(os.getpid())
    execvp.assert_called_once_with("unshare", [
        "unshare", "--user", "--map-root-user", "--net", "/bundle/polmon",
        "--run-vm", "mixed-helper", "active", str(ready),
    ])


def test_mixed_create_rolls_back_on_fd_export_failure(backend, topology, monkeypatch):
    def vm_create(self, selected):
        self.lab = self._make_lab(selected)
        self.phase = "created"
        return set()
    monkeypatch.setattr(VMBackend, "create", vm_create)
    backend._export_fd = Mock(side_effect=VMError("vm.mixed_start_failed"))
    backend.destroy = Mock()
    with pytest.raises(VMError, match="vm.mixed_start_failed"):
        backend.create(topology)
    backend.destroy.assert_called_once()


def test_start_checks_phase_before_starting_any_peer(backend):
    backend.transport.synthetic.start = Mock()
    with pytest.raises(VMError, match="vm.not_created"):
        backend.start()
    backend.transport.synthetic.start.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="Linux namespace FD ownership contract")
def test_service_thread_start_failure_closes_exported_socket(backend, topology, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        descriptor = os.dup(listener.fileno())
        backend._export_fd = Mock(return_value=descriptor)
        monkeypatch.setattr(mixed, "Thread", lambda **_: SimpleNamespace(
            start=Mock(side_effect=RuntimeError("thread unavailable")),
        ))
        with pytest.raises(RuntimeError, match="thread unavailable"):
            backend._start_http(topology.nodes[1])
        assert not backend.http_servers
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_service_start_failure_stops_existing_peers(backend, topology, monkeypatch):
    backend.validate(topology)
    backend.phase = "created"
    backend._start_http = Mock(side_effect=RuntimeError("socket unavailable"))
    backend.stop = Mock()
    vm_start = Mock()
    monkeypatch.setattr(VMBackend, "start", vm_start)
    with pytest.raises(RuntimeError, match="socket unavailable"):
        backend.start()
    backend.stop.assert_called_once()
    vm_start.assert_not_called()


def test_failed_namespace_readiness_does_not_leave_ready_journal(backend, topology, monkeypatch):
    backend.validate(topology)
    backend.phase = "started"
    backend.topology = backend.vm_topology
    backend.identities["guest"] = (12344, "1")
    backend.holders["namespace"] = (12345, "1")
    backend._node_ready = Mock(return_value=True)
    backend._journal = Mock()
    monkeypatch.setattr(vm_module, "alive", lambda _: True)
    monkeypatch.setattr(mixed, "alive", lambda _: False)
    with pytest.raises(VMError, match="vm.mixed_start_failed"):
        backend.wait_ready()
    assert backend.ready is False
    backend._journal.assert_not_called()


def test_mixed_readiness_is_journaled_only_after_all_peers_pass(backend, topology, monkeypatch):
    backend.validate(topology)
    backend.phase = "started"
    backend.topology = backend.vm_topology
    backend.identities["guest"] = (12344, "1")
    backend.holders["namespace"] = (12345, "1")
    checked = []

    def node_ready(node):
        assert backend.ready is False
        checked.append(node.id)
        return True

    def journal():
        assert backend.ready is True
        assert checked == ["guest", "namespace"]

    backend._node_ready = node_ready
    backend._journal = Mock(side_effect=journal)
    monkeypatch.setattr(vm_module, "alive", lambda _: True)
    monkeypatch.setattr(mixed, "alive", lambda _: True)
    backend.wait_ready()
    backend._journal.assert_called_once()


def test_mixed_seed_reports_guest_to_namespace_http_and_guest_to_l0_ping(topology):
    import yaml

    document = yaml.safe_load(
        seed_documents(topology.nodes[0], topology, peer_report=True)["user-data"],
    )
    commands = json.dumps(document["runcmd"])
    assert "namespace" in commands and "192.168.239.12" in commands
    assert "synthetic" in commands and "192.168.239.13" in commands
    scripts = {file["path"]: file["content"] for file in document["write_files"]}
    assert "subprocess.run" in scripts["/usr/local/bin/polmon-pings.py"]
    without_report = seed_documents(topology.nodes[0], topology)["user-data"]
    assert "polmon-pings.py" not in without_report


def test_mixed_plan_cli_opt_in(backend, capsys):
    from polmon_l1_vm.cli import main

    assert main([
        "plan", "--topology", str(ROOT / "examples/topologies/l1-vm-mixed.yml"),
        "--directory", str(backend.directory), "--image", str(backend.base),
        "--manifest", str(ROOT / "examples/vm/alpine-3.24.1-manifest.json"),
        "--vm-node", "guest",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["namespace_nodes"] == ["namespace"]


def test_real_cli_run_report_probes_full_topology_with_mock_lifecycle(backend, monkeypatch, capsys):
    """Real CLI parser/report path; no additional KVM boot is claimed by this unit test."""
    from polmon_l1_vm.cli import main

    created = []
    destroyed = []

    def create(instance, topology):
        instance.validate(topology)
        instance.topology = instance.vm_topology
        created.append(instance)

    def fetch(instance, address, port, path="/"):
        node = next(n for n in instance.full_topology.nodes if str(n.interfaces[0].ipv4) == address)
        return 200, f"POLMON {node.id} {node.uuid}\n"

    monkeypatch.setattr(MixedBackend, "create", create)
    monkeypatch.setattr(MixedBackend, "start", lambda _: None)
    monkeypatch.setattr(MixedBackend, "wait_ready", lambda _: None)
    monkeypatch.setattr(MixedBackend, "fetch_http", fetch)
    monkeypatch.setattr(MixedBackend, "destroy", lambda instance: destroyed.append(instance))
    monkeypatch.setattr(VMBackend, "sample", lambda _: {"nodes": {"guest": {"pid": None}}})
    assert main([
        "run", "--topology", str(ROOT / "examples/topologies/l1-vm-mixed.yml"),
        "--directory", str(backend.directory), "--image", str(backend.base),
        "--manifest", str(ROOT / "examples/vm/alpine-3.24.1-manifest.json"),
        "--vm-node", "guest",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["probes"] == {"guest": [True], "namespace": [True], "synthetic": []}
    assert report["sample"]["mixed"]["vm_nodes"] == ["guest"]
    assert report["sample"]["nodes"] == {"guest": {"pid": None}}
    assert created == destroyed
