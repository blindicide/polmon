import sys

import pytest

from polmon.backends.namespace.runner import TIMEOUT_RETURNCODE, CommandRunner

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
