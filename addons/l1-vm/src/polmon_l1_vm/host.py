"""Сведения о хосте: память, диск, идентичность процессов и допуск запуска."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import time
from pathlib import Path

from polmon_l1_vm.images import VMError

PER_VM_OVERHEAD_MB = 64  # оценка накладных расходов QEMU сверх памяти гостя, не измерение


def process_start(pid: int) -> str | None:
    """Время старта из /proc: вместе с pid защищает от повторного использования pid."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[19]


def alive(identity: tuple[int, str] | list) -> bool:
    return process_start(int(identity[0])) == identity[1]


def terminate(identity: tuple[int, str] | list, *, grace: float = 3.0) -> bool:
    """Останавливает процесс только если pid всё ещё принадлежит записанному процессу."""
    pid = int(identity[0])
    if not alive(identity):
        return False
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, grace)):
        with contextlib.suppress(OSError):
            os.kill(pid, sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            # Зомби (ещё не прибранный родителем) считается завершённым.
            if not alive(identity) or _zombie(pid):
                return True
            time.sleep(0.05)
    return not alive(identity)


def _zombie(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True
    return stat.rsplit(")", 1)[1].split()[0] == "Z"


def memory_available_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def admit(
    *,
    count: int,
    memory_mb: int,
    memory_reserve_mb: int,
    directory: Path,
    disk_reserve_mb: int,
    max_total_disk_mb: int,
    virtual_bytes: int,
) -> dict:
    """Отказывает до создания ресурсов, если памяти или диска не хватает с учётом запаса."""
    requested_memory = count * (memory_mb + PER_VM_OVERHEAD_MB)
    available = memory_available_mb()
    if available is None or available < requested_memory + memory_reserve_mb:
        raise VMError("vm.host_memory")
    # Худший случай роста перекрытия — полный виртуальный размер базового образа.
    worst_disk_mb = count * -(-virtual_bytes // 1_048_576)
    if worst_disk_mb > max_total_disk_mb:
        raise VMError("vm.disk_limit")
    probe = directory
    while not probe.exists():
        probe = probe.parent
    free_mb = shutil.disk_usage(probe).free // 1_048_576
    if free_mb < worst_disk_mb + disk_reserve_mb:
        raise VMError("vm.host_disk")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise VMError("vm.kvm_unavailable")
    return {
        "requested_memory_mb": requested_memory,
        "host_available_memory_mb": available,
        "worst_case_disk_mb": worst_disk_mb,
        "host_free_disk_mb": free_mb,
    }
