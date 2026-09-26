from pathlib import Path

import pytest

from polmon.backends.hybrid.backend import HybridBackend
from polmon.backends.namespace.runner import CommandResult
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/hybrid-tap.yml"


class FakeProcess:
    pid = 1

    def poll(self):
        return 0


class FakeRunner:
    def __init__(self) -> None:
        self.commands = []

    def run(self, command, *, privileged=False, check=True, timeout=10):
        self.commands.append(command)
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        self.commands.append(command)
        return FakeProcess()


class FakeTap:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    def write(self, frame: bytes) -> None:
        pass

    def read(self, timeout: float):
        return None

    def close(self) -> None:
        self.closed = True


def test_hybrid_uses_one_shared_tap_and_tears_it_down_first() -> None:
    runner = FakeRunner()
    taps = []

    def factory(name):
        tap = FakeTap(name)
        taps.append(tap)
        return tap

    backend = HybridBackend(
        runner=runner,
        tap_factory=factory,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=lambda bridge: {tap.name: "3" for tap in taps},
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    resources = backend.create(topology)
    assert any(command[-2:] == ["user", "1000"] for command in runner.commands)
    assert len([resource for resource in resources if resource.startswith("tap:")]) == 1
    assert len(backend.synthetic.engine.endpoints) == 1
    backend.destroy()
    assert taps[0].closed
    link_deletes = [
        (index, command)
        for index, command in enumerate(runner.commands)
        if command[:4] == ["ip", "link", "del", "dev"]
    ]
    tap_delete_index = next(
        index for index, command in link_deletes if command[-1] == taps[0].name
    )
    bridge_delete_index = max(index for index, _ in link_deletes)
    assert tap_delete_index < bridge_delete_index


def test_hybrid_create_waits_until_bridge_ports_forward() -> None:
    runner = FakeRunner()
    polls = []

    def states(bridge: str) -> dict[str, str]:
        polls.append(bridge)
        tap_name = next(iter(backend.tap_names.values()))
        # First two polls: the TAP port is still disabled after attach (linkwatch race).
        return {tap_name: "0" if len(polls) <= 2 else "3", "vethpeer": "3"}

    backend = HybridBackend(
        runner=runner,
        tap_factory=FakeTap,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=states,
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    backend.create(topology)
    assert len(polls) == 3
    backend.destroy()


def test_hybrid_create_fails_closed_and_cleans_up_when_port_never_forwards() -> None:
    runner = FakeRunner()
    taps = []

    def factory(name):
        tap = FakeTap(name)
        taps.append(tap)
        return tap

    backend = HybridBackend(
        runner=runner,
        tap_factory=factory,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
        bridge_port_states=lambda bridge: {tap.name: "0" for tap in taps},
        port_ready_timeout=0.05,
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    with pytest.raises(Exception, match="forwarding state"):
        backend.create(topology)
    assert taps[0].closed
    assert not backend.taps and not backend.tap_names
    assert any(
        command[:4] == ["ip", "link", "del", "dev"] and command[-1] == taps[0].name
        for command in runner.commands
    )
