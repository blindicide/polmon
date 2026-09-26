import sys
from pathlib import Path

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

    def run(self, command, *, privileged=False, check=True, timeout=10):
        self.commands.append((command, privileged, check))
        return CommandResult("", "", 0)

    def start(self, command, *, privileged=False):
        self.commands.append((command, privileged, True))
        return FakeProcess()


def test_namespace_command_plan_is_isolated_and_cleanup_is_idempotent() -> None:
    runner = FakeRunner()
    backend = NamespaceBackend(
        runner=runner, python_executable=sys.executable, require_linux=False
    )
    topology = load_topology(EXAMPLE)
    backend.validate(topology)
    resources = backend.create(topology)
    backend.start()
    backend.destroy()
    backend.destroy()
    assert len([resource for resource in resources if resource.startswith("netns:")]) == 2
    assert len([resource for resource in resources if resource.startswith("bridge:")]) == 1
    assert all(privileged for _, privileged, _ in runner.commands)
    assert all(command[0] == "ip" for command, _, _ in runner.commands)
    joined = " ".join(part for command, _, _ in runner.commands for part in command)
    assert "iptables" not in joined and "nft" not in joined and "default" not in joined
    assert all(
        len(part) <= 15
        for command, _, _ in runner.commands
        for part in command
        if part.startswith(("polmon", "veth"))
    )
