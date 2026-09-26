"""The Phase I target demonstration against a real local backend and laboratory."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from polmon import demo


def lab_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv")):
        return False
    if not Path("/dev/net/tun").exists():
        return False
    return subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    ).returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_mvp_demonstration_passes_end_to_end(tmp_path) -> None:
    if not lab_available():
        pytest.skip("NOT RUN — environment unavailable: TAP and namespace privileges required")
    code = demo.main(["--experiment-id", "mvp-test", "--output-dir", str(tmp_path)])
    record = json.loads((tmp_path / "mvp-test.json").read_text(encoding="utf-8"))
    assert code == 0, record.get("error")
    assert record["deployment"]["resource_counts"]["synthetic"] == 50
    assert record["deployment"]["resource_counts"]["netns"] == 2
    paths = {item["path"] for item in record["experiment"]["observations"]}
    assert paths == {"l0->l1", "l0->l0", "l1->l1"}
    assert all(item["success"] for item in record["experiment"]["observations"])
    assert record["telemetry"]["capture"]["frame_count"] > 0
    assert record["cleanup"] == {
        "active_deployments": 0,
        "checked_locally": True,
        "remaining_lab_resources": [],
    }
    assert record["backend_shutdown"]["shutdown_cleanup_logged"] is True
    assert (tmp_path / "mvp-test-report.md").read_text(encoding="utf-8").startswith(
        "# Experiment mvp-test"
    )
