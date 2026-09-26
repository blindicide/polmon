import sys
from pathlib import Path

import pytest

from polmon.backends.namespace.backend import NamespaceBackend
from polmon.backends.namespace.runner import CommandResult
from polmon.topology import load_topology

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml"


class FakeProcess:
    pid = 123

    def poll(self):
        return 0


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[list[str], bool, bool]] = []

    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
        if input is not None:  # expand `ip [-n NS] [-force] -batch -` into per-line commands
            base = [part for part in command if part not in ("-batch", "-", "-force")]
            for line in input.splitlines():
                self.commands.append(([*base, *line.split()], privileged, check))
            return CommandResult("", "", 0)
        self.commands.append((command, privileged, check))
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        self.commands.append((command, privileged, True))
        return FakeProcess()


def test_namespace_command_plan_is_isolated_and_cleanup_is_idempotent() -> None:
    runner = FakeRunner()
    backend = NamespaceBackend(
        runner=runner,
        python_executable=sys.executable,
        require_linux=False,
        owner_uid=1000,
        owner_gid=1001,
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    resources = backend.create(topology)
    backend.start()
    backend.destroy()
    backend.destroy()
    assert len([resource for resource in resources if resource.startswith("netns:")]) == 2
    assert len([resource for resource in resources if resource.startswith("bridge:")]) == 1
    read_only = {("ip", "-o", "link", "show"), ("ip", "netns", "list")}
    rootless = [tuple(command) for command, privileged, _ in runner.commands if not privileged]
    assert set(rootless) <= read_only  # only read-only preflight queries run without sudo
    assert all(command[0] == "ip" for command, _, _ in runner.commands)
    joined = " ".join(part for command, _, _ in runner.commands for part in command)
    assert "--reuid 1000 --regid 1001" in joined
    assert "iptables" not in joined and "nft" not in joined and "default" not in joined
    assert all(
        len(part) <= 15
        for command, _, _ in runner.commands
        for part in command
        if part.startswith(("polmon", "veth"))
    )


class BatchRecorder:
    """Records raw privileged calls (one per sudo invocation) and can fail a chosen call."""

    def __init__(self, fail_call: int | None = None) -> None:
        self.calls: list[tuple[list[str], str | None, bool]] = []
        self.fail_call = fail_call

    def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
        if not privileged:  # rootless preflight queries report an empty host
            return CommandResult("", "", 0)
        self.calls.append((command, input, check))
        if self.fail_call is not None and len(self.calls) == self.fail_call:
            raise RuntimeError("command failed (1): ip: injected failure")
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        return FakeProcess()


def test_create_uses_one_privileged_batch_per_namespace_plus_host() -> None:
    runner = BatchRecorder()
    backend = NamespaceBackend(runner=runner, require_linux=False, owner_uid=1, owner_gid=1)
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    backend.create(topology)
    assert len(runner.calls) == 1 + len(topology.nodes)
    host_command, host_input, _ = runner.calls[0]
    assert host_command == ["ip", "-batch", "-"]
    assert "netns add" in host_input and "type veth peer name" in host_input
    for command, lines, _ in runner.calls[1:]:
        assert command[:2] == ["ip", "-n"] and command[-2:] == ["-batch", "-"]
        assert "address add" in lines


def test_failed_batch_rolls_back_every_planned_object_including_host_veths() -> None:
    runner = BatchRecorder(fail_call=1)  # the host batch fails part-way
    backend = NamespaceBackend(runner=runner, require_linux=False, owner_uid=1, owner_gid=1)
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    try:
        backend.create(topology)
    except RuntimeError:
        pass
    else:
        raise AssertionError("create should propagate the batch failure")
    command, teardown, check = runner.calls[-1]
    assert command == ["ip", "-force", "-batch", "-"] and check is False
    for veth in backend.names.host_veths.values():
        assert f"link del dev {veth}" in teardown  # a veth that never moved is not leaked
    for namespace in backend.names.namespaces.values():
        assert f"netns del {namespace}" in teardown
    assert not backend.inspect().resources


def test_create_refuses_to_adopt_objects_it_did_not_create() -> None:
    topology = load_topology(EXAMPLE)
    probe = NamespaceBackend(runner=BatchRecorder(), require_linux=False, owner_uid=1, owner_gid=1)
    taken = probe._names(topology).namespaces["server"]

    class Occupied(BatchRecorder):
        def run(self, command, *, privileged=False, check=True, timeout=10, input=None):
            if command == ["ip", "netns", "list"]:
                return CommandResult(f"{taken} (id: 3)\n", "", 0)
            return super().run(
                command, privileged=privileged, check=check, timeout=timeout, input=input
            )

    runner = Occupied()
    backend = NamespaceBackend(runner=runner, require_linux=False, owner_uid=1, owner_gid=1)
    backend.validate(topology)
    try:
        backend.create(topology)
    except RuntimeError as error:
        assert taken in str(error)
    else:
        raise AssertionError("create must refuse a pre-existing generated name")
    assert runner.calls == []  # nothing created, nothing deleted
    assert not backend.inspect().resources


def test_every_in_namespace_workload_runs_as_the_owner_not_root() -> None:
    runner = FakeRunner()
    backend = NamespaceBackend(runner=runner, require_linux=False, owner_uid=1000, owner_gid=1001)
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    backend.create(topology)
    backend.start()
    backend.ping("client", "10.88.0.20")
    backend.probe_tcp("client", "10.88.0.20", 8080)
    with pytest.raises(ValueError):  # the fake runner prints no ping summary
        backend.ping_statistics("client", "10.88.0.20", count=1)
    executions = [command for command, _, _ in runner.commands if command[1:3] == ["netns", "exec"]]
    assert len(executions) == 4  # service, ping, probe, ping statistics
    for command in executions:
        assert command[4:10] == ["setpriv", "--reuid", "1000", "--regid", "1001", "--clear-groups"]
    backend.destroy()
