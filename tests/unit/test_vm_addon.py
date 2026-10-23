"""VM planning/failure tests are not evidence of a booted guest."""

import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from polmon_l1_vm import backend as module
from polmon_l1_vm import images
from polmon_l1_vm.backend import VMBackend, VMLimits, readiness
from polmon_l1_vm.cli import main
from polmon_l1_vm.images import (
    ImageManifest,
    OverlayStore,
    VMError,
    acquire_image,
    verify_image,
)
from polmon_l1_vm.seed import SEED_VOLUME_ID, create_seed, seed_documents

from polmon.backends.namespace.runner import CommandResult, CommandRunner
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


def manifest(sha="0" * 64):
    return ImageManifest(
        sha256=sha,
        source_url="https://example.invalid/pinned-test.qcow2",
        distribution="alpine-3.23.0-x86_64-bios-cloudinit",
        license_notice="Test fixture only, not a Linux guest image",
    )


def backend(tmp_path, **kwargs):
    return VMBackend(
        base=tmp_path / "base.qcow2", manifest=manifest(), directory=tmp_path / "run", **kwargs
    )


def test_optional_readiness_is_explicit(monkeypatch, capsys):
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    result = readiness()
    assert not result["ready"] and "vm.qemu_missing" in result["missing"]
    assert main(["readiness"]) == 2
    assert not json.loads(capsys.readouterr().out)["ready"]


def test_model_limits_and_namespace_semantics(tmp_path):
    topology = load_topology(EXAMPLE)
    vm = backend(tmp_path)
    vm.validate(topology)
    assert topology.estimate_resources().l1_namespaces == 2
    with pytest.raises(VMError, match="vm.node_limit"):
        backend(tmp_path, limits=VMLimits(max_vms=1)).validate(topology)
    with pytest.raises(VMError, match="vm.memory_limit"):
        backend(tmp_path, limits=VMLimits(memory_mb=512)).validate(topology)
    topology.nodes[0].node_class = "l0"
    with pytest.raises(VMError, match="vm.l1_only"):
        vm.validate(topology)


def test_readiness_reports_runtime_and_modes(monkeypatch):
    monkeypatch.setattr(module, "_userns_works", lambda: True)
    monkeypatch.setattr(module, "_sudo_works", lambda: False)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(module.os, "access", lambda *args: True)
    result = readiness()
    assert result["ready"] and result["runtime_implemented"]
    assert result["modes"] == {"userns": True, "netns": False}
    assert result["missing"] == []
    monkeypatch.setattr(module, "_userns_works", lambda: False)
    result = readiness()
    assert not result["ready"]
    assert {"vm.userns_unavailable", "vm.sudo_unavailable"} <= set(result["missing"])
    monkeypatch.setattr(module.os, "access", lambda *args: False)
    assert {"vm.kvm_unavailable", "vm.tun_unavailable"} <= set(readiness()["missing"])


def test_lifecycle_refuses_before_mutation(tmp_path):
    runner = FakeRunner()
    vm = backend(tmp_path, runner=runner)
    topology = load_topology(EXAMPLE)
    for action in (vm.start, vm.wait_ready, vm.sample):
        with pytest.raises(VMError, match="vm.not_"):
            action()
    with pytest.raises(VMError, match="vm.not_created"):
        vm.probe_http("192.168.236.20", 8080, "server")
    # Образа нет: отказ происходит до создания каталога, пространства и дисков.
    with pytest.raises(VMError, match="vm.image_missing"):
        vm.create(topology)
    vm.stop()
    vm.destroy()
    vm.destroy()  # повторный вызов безопасен
    assert not runner.calls
    assert not list(tmp_path.iterdir())
    assert not vm.inspect().resources
    # Непустой каталог запуска чужой: он не используется и не затирается.
    fresh = backend(tmp_path, runner=runner)
    fresh.directory.mkdir()
    (fresh.directory / "operator.txt").write_text("keep")
    with pytest.raises(VMError, match="vm.directory_not_empty"):
        fresh.create(topology)
    assert (fresh.directory / "operator.txt").read_text() == "keep"
    assert not runner.calls


def test_generated_seed_addresses_identity_and_no_egress():
    topology = load_topology(EXAMPLE)
    first, second = [seed_documents(node, topology) for node in topology.nodes]
    assert first["meta-data"] != second["meta-data"]
    assert str(topology.nodes[0].uuid) in first["meta-data"]
    assert "192.168.236.10/24" in first["network-config"]
    assert "gateway" not in first["network-config"] and "dns" not in first["network-config"]
    assert "package_update: false" in first["user-data"]
    assert "http.server" in second["user-data"]


def test_clone_and_network_plans_keep_distinct_identities(tmp_path):
    vm = backend(tmp_path)
    topology = load_topology(EXAMPLE)
    plan = vm.plan(topology)
    assert plan["runtime_implemented"]
    assert plan["estimated_memory_mb"] == 640
    assert len({node["uuid"] for node in plan["nodes"]}) == 2
    assert len({node["overlay"] for node in plan["nodes"]}) == 2
    assert "no host uplink" in plan["network"]
    assert not vm.directory.exists()


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.namespace_exists = False

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[:3] == ["ip", "netns", "add"]:
            self.namespace_exists = True
        if argv[:3] == ["ip", "netns", "del"]:
            self.namespace_exists = False
        return CommandResult("", "", 0)


def test_real_qcow_clone_storage_isolation(tmp_path):
    """Real qemu-img/qemu-io, but intentionally not a guest or VM integration test."""
    if not shutil.which("qemu-img") or not shutil.which("qemu-io"):
        pytest.skip("NOT RUN — environment unavailable: qemu-img/qemu-io")
    runner = CommandRunner()
    base = tmp_path / "base.qcow2"
    runner.run(["qemu-img", "create", "-q", "-f", "qcow2", str(base), "16M"])
    base.chmod(0o444)
    sha = hashlib.sha256(base.read_bytes()).hexdigest()
    verified = verify_image(base, manifest(sha), runner)
    store = OverlayStore(tmp_path, base, runner)
    left, right = store.create("alpha"), store.create("bravo")
    runner.run(["qemu-io", "-f", "qcow2", "-c", "write -P 0x41 0 4096", str(left)])
    runner.run(["qemu-io", "-r", "-f", "qcow2", "-c", "read -P 0x41 0 4096", str(left)])
    for path in (base, right):
        runner.run(["qemu-io", "-r", "-f", "qcow2", "-c", "read -P 0 0 4096", str(path)])
    assert hashlib.sha256(base.read_bytes()).hexdigest() == sha
    print(
        "QCOW-STORAGE-EVIDENCE",
        json.dumps(
            {
                "base": verified,
                "alpha_allocated_bytes": left.stat().st_blocks * 512,
                "bravo_allocated_bytes": right.stat().st_blocks * 512,
            }
        ),
    )
    store.destroy()
    assert not left.exists() and not right.exists() and base.exists()
    with pytest.raises(VMError, match="vm.image_checksum"):
        verify_image(base, manifest(), runner)


def test_overlay_never_overwrites_existing_file(tmp_path):
    target = tmp_path / "alpha.qcow2"
    target.write_bytes(b"operator-file")
    store = OverlayStore(tmp_path, tmp_path / "base", FakeRunner())
    with pytest.raises(FileExistsError):
        store.create("alpha")
    store.destroy()
    assert target.read_bytes() == b"operator-file"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_acquire_image_verifies_before_publishing_read_only(tmp_path):
    data = b"qcow2-bytes" * 1000
    good = manifest(hashlib.sha256(data).hexdigest())
    target = tmp_path / "images" / "base.qcow2"
    result = acquire_image(target, good, opener=lambda url: FakeResponse(data))
    assert result["bytes"] == len(data) and target.read_bytes() == data
    assert target.stat().st_mode & 0o777 == 0o444
    assert [item.name for item in target.parent.iterdir()] == ["base.qcow2"]
    with pytest.raises(VMError, match="vm.image_exists"):
        acquire_image(target, good, opener=lambda url: FakeResponse(b"other"))
    assert target.read_bytes() == data


def test_acquire_image_rejects_bad_digest_oversize_and_leaves_nothing(tmp_path):
    data = b"x" * 4096
    cases = [
        (manifest("0" * 64), data, "vm.image_checksum"),
        (
            manifest(hashlib.sha256(data).hexdigest()).model_copy(update={"max_file_bytes": 1024}),
            data,
            "vm.image_size",
        ),
    ]
    for item, payload, code in cases:
        with pytest.raises(VMError, match=code):
            acquire_image(
                tmp_path / "base.qcow2", item, opener=lambda url, p=payload: FakeResponse(p)
            )
        assert not list(tmp_path.iterdir())

    def broken(url):
        raise OSError("network down")

    with pytest.raises(VMError, match="vm.image_download"):
        acquire_image(tmp_path / "base.qcow2", manifest(), opener=broken)
    assert not list(tmp_path.iterdir())


def test_acquisition_refuses_redirect_to_plain_http():
    handler = images._HttpsOnly()
    with pytest.raises(VMError, match="vm.image_redirect"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://example.invalid/x")


def test_cli_inspection_recovery_and_image_commands(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    assert main(["inspect", "--directory", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "absent"
    assert main(["recover", "--directory", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] is False
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest().model_dump_json())
    arguments = ["--manifest", str(manifest_path), "--image", str(tmp_path / "absent")]
    assert main(["verify-image", *arguments]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "vm.image_missing"
    manifest_path.write_text("x" * 20000)
    assert main(["verify-image", *arguments]) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "vm.manifest_size"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["manifest.json", "run"]


def test_seed_iso_is_created_with_nocloud_label_and_documents(tmp_path):
    if not shutil.which("genisoimage") or not shutil.which("isoinfo"):
        pytest.skip("NOT RUN — environment unavailable: genisoimage/isoinfo")
    topology = load_topology(EXAMPLE)
    node = topology.nodes[0]
    path = create_seed(tmp_path, node, topology, CommandRunner())
    assert path == tmp_path / f"{node.id}-seed.iso"
    # Метка тома — позиция 0x8028 первичного дескриптора ISO 9660.
    assert path.read_bytes()[0x8028:0x8048].decode().strip() == SEED_VOLUME_ID
    runner = CommandRunner()
    listing = runner.run(["isoinfo", "-R", "-l", "-i", str(path)]).stdout
    for name in ("meta-data", "user-data", "network-config"):
        assert name in listing
    user_data = runner.run(["isoinfo", "-R", "-x", "/user-data", "-i", str(path)]).stdout
    assert user_data == seed_documents(node, topology)["user-data"]
    # Рабочий каталог удалён, остался только образ.
    assert [item.name for item in tmp_path.iterdir()] == [path.name]


def test_seed_refuses_existing_file_and_cleans_up_on_failure(tmp_path):
    topology = load_topology(EXAMPLE)
    node = topology.nodes[0]
    (tmp_path / f"{node.id}-seed.iso").write_bytes(b"operator-file")
    with pytest.raises(FileExistsError):
        create_seed(tmp_path, node, topology, FakeRunner())
    assert (tmp_path / f"{node.id}-seed.iso").read_bytes() == b"operator-file"

    class Failing(FakeRunner):
        def run(self, argv, **kwargs):
            raise RuntimeError("genisoimage failed")

    (tmp_path / f"{node.id}-seed.iso").unlink()
    with pytest.raises(RuntimeError):
        create_seed(tmp_path, node, topology, Failing())
    assert not list(tmp_path.iterdir())
    node.id = "Bad_ID"
    with pytest.raises(VMError, match="vm.node_id"):
        create_seed(tmp_path, node, topology, FakeRunner())
