"""Лабораторная сеть ВМ: имена, план команд и настоящее непривилегированное пространство."""

import ipaddress
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from polmon_l1_vm.images import VMError
from polmon_l1_vm.lab import Lab, lab_names, probe_address

from polmon.backends.namespace.runner import CommandResult, CommandRunner
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-vm-addon.yml"


class RecordingRunner:
    def __init__(self, listing=""):
        self.calls = []
        self.listing = listing

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return CommandResult(self.listing if argv[:3] == ["ip", "netns", "list"] else "", "", 0)


def test_names_are_deterministic_short_and_platform_prefixed():
    topology = load_topology(EXAMPLE)
    names = lab_names(topology)
    assert names == lab_names(topology)
    everything = [names.namespace, *names.bridges.values(), *names.taps.values()]
    assert len(set(everything)) == len(everything) == 4
    assert all(item.startswith("polmon") and len(item) <= 15 for item in everything)
    assert names.namespace.endswith("n")
    assert all(item.endswith("b") for item in names.bridges.values())
    assert all(item.endswith("t") for item in names.taps.values())


def test_probe_address_is_free_and_inside_the_subnet():
    topology = load_topology(EXAMPLE)
    probe = probe_address(topology, "lab")
    assert str(probe) == "192.168.240.254/24"
    topology.nodes[0].interfaces[0].ipv4 = ipaddress.IPv4Address("192.168.240.254")
    assert str(probe_address(topology, "lab")) == "192.168.240.253/24"


def test_netns_mode_plan_is_privileged_owned_and_has_no_uplink():
    topology = load_topology(EXAMPLE)
    runner = RecordingRunner()
    lab = Lab(topology, runner, mode="netns", owner_uid=1000, owner_gid=1001)
    # Проверку изоляции на пустом фиктивном выводе пропускаем: нужен только план команд.
    lab.verify_isolated = lambda: {}
    lab.create()
    add = runner.calls[1]
    assert add[0] == ["ip", "netns", "add", lab.names.namespace] and add[1]["privileged"]
    batch_argv, batch_kwargs = runner.calls[2]
    assert batch_argv[:4] == ["ip", "netns", "exec", lab.names.namespace]
    assert batch_kwargs["privileged"]
    lines = batch_kwargs["input"].splitlines()
    assert "link set lo up" in lines
    assert f"link add name {lab.names.bridges['lab']} type bridge" in lines
    assert f"addr add 192.168.240.254/24 dev {lab.names.bridges['lab']}" in lines
    taps = [line for line in lines if line.startswith("tuntap add")]
    assert len(taps) == 2 and all("user 1000 group 1001" in line for line in taps)
    assert not any("route" in line or "nat" in line for line in lines)
    assert lab.resources() == {f"netns:{lab.names.namespace}"}
    lab.destroy()
    assert runner.calls[-1][0] == ["ip", "netns", "del", lab.names.namespace]
    assert not lab.resources()


def test_netns_mode_never_adopts_an_existing_namespace():
    topology = load_topology(EXAMPLE)
    names = lab_names(topology)
    runner = RecordingRunner(listing=f"{names.namespace} (id: 0)\n")
    lab = Lab(topology, runner, mode="netns")
    with pytest.raises(VMError, match="vm.lab_exists"):
        lab.create()
    assert [call[0][:3] for call in runner.calls] == [["ip", "netns", "list"]]


def test_owner_commands_drop_privileges_and_vm_processes_are_hardened():
    topology = load_topology(EXAMPLE)
    lab = Lab(topology, RecordingRunner(), mode="netns", owner_uid=1000, owner_gid=1000)
    argv = lab.wrap(["qemu-system-x86_64"], as_owner=True, harden=True)
    assert argv[:4] == ["ip", "netns", "exec", lab.names.namespace]
    assert argv[4:6] == ["setpriv", "--reuid"]
    assert "--clear-groups" in argv and "--no-new-privs" in argv
    assert "--no-new-privs" not in lab.wrap(["ping"], as_owner=True)
    with pytest.raises(VMError, match="vm.lab_missing"):
        Lab(topology, RecordingRunner()).wrap(["true"])
    with pytest.raises(VMError, match="vm.mode_invalid"):
        Lab(topology, RecordingRunner(), mode="docker")


def _userns_available():
    if not shutil.which("unshare") or not shutil.which("nsenter") or not shutil.which("ip"):
        return False
    return subprocess.run(["unshare", "-Urn", "true"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _userns_available(), reason="NOT RUN — userns/unshare/nsenter unavailable")
def test_real_userns_lab_creates_isolated_devices_and_leaves_nothing():
    topology = load_topology(EXAMPLE)
    host_links = subprocess.run(["ip", "-o", "link"], capture_output=True, text=True).stdout
    lab = Lab(topology, CommandRunner(), mode="userns")
    lab.create()
    try:
        pid = lab.holder.pid
        assert os.readlink(f"/proc/{pid}/ns/net") != os.readlink("/proc/self/ns/net")
        links = lab.run(["ip", "-o", "link", "show"]).stdout
        for name in (*lab.names.bridges.values(), *lab.names.taps.values()):
            assert name in links
        # Мост несёт адрес опроса; маршрута наружу нет.
        addresses = lab.run(["ip", "-o", "-4", "addr", "show"]).stdout
        assert "192.168.240.254/24" in addresses
        assert lab.run(["ip", "-4", "route", "show"]).stdout.count("default") == 0
        assert lab.verify_isolated()["namespace"] == lab.names.namespace
        assert lab.resources() == {f"userns:{pid}"}
        # Ничего из лаборатории не видно в сетевом пространстве хоста.
        now = subprocess.run(["ip", "-o", "link"], capture_output=True, text=True).stdout
        assert now == host_links
    finally:
        lab.destroy()
    assert lab.holder is None and not lab.resources()
    assert (
        not Path(f"/proc/{pid}").exists() or Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
    )
    lab.destroy()  # повторный вызов безопасен
