import os
import subprocess
import sys
import time

import pytest

from polmon.backends.namespace.runner import TIMEOUT_RETURNCODE, CommandRunner, stop_process_group

SLEEPER = [sys.executable, "-c", "import time; time.sleep(5)"]


def test_timeout_without_check_returns_a_result_for_best_effort_teardown() -> None:
    result = CommandRunner().run(SLEEPER, check=False, timeout=0.2)
    assert result.returncode == TIMEOUT_RETURNCODE
    assert "timed out" in result.stderr


def test_timeout_with_check_raises_a_clear_error() -> None:
    with pytest.raises(RuntimeError, match="timed out after 0.2s"):
        CommandRunner().run(SLEEPER, timeout=0.2)


def test_failures_raise_only_when_checked() -> None:
    failing = [sys.executable, "-c", "import sys; sys.exit(3)"]
    assert CommandRunner().run(failing, check=False).returncode == 3
    with pytest.raises(RuntimeError, match=r"command failed \(3\)"):
        CommandRunner().run(failing)


def test_bounded_runner_caps_output_and_times_out() -> None:
    noisy = [sys.executable, "-c", "print('x' * 10000)"]
    result = CommandRunner().run_bounded(noisy, max_output_bytes=128)
    assert len(result.stdout.encode()) == 128 and result.truncated is True
    sleeper = CommandRunner().run_bounded(SLEEPER, timeout=0.1)
    assert sleeper.timed_out is True and sleeper.returncode == TIMEOUT_RETURNCODE


def test_stop_reaps_child_without_posix_process_groups(monkeypatch) -> None:
    monkeypatch.delattr(os, "killpg", raising=False)
    process = subprocess.Popen(SLEEPER)
    try:
        stop_process_group(process, grace=0.2)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def test_service_log_is_written_while_the_process_is_still_running(tmp_path) -> None:
    # Короткий вывод не должен ждать полного блока: консоль гостя нужна, пока он жив.
    log = tmp_path / "service.log"
    process = CommandRunner().start(
        [sys.executable, "-u", "-c", "import time; print('ready', flush=True); time.sleep(30)"],
        log_path=log,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "ready" not in log.read_text(errors="replace"):
            time.sleep(0.05)
        assert "ready" in log.read_text()
    finally:
        stop_process_group(process, grace=1)
