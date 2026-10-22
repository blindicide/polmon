"""Recovery extension boundary; no VM ownership or cleanup has been validated."""

from pathlib import Path

from polmon.backends.namespace.runner import CommandRunner
from polmon_l1_vm.images import VMError


def inspect_run(directory: Path) -> dict:
    raise VMError("vm.scaffold_only")


def recover(directory: Path, runner: CommandRunner | None = None) -> dict:
    raise VMError("vm.scaffold_only")
