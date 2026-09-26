"""A controlled experiment on a real hybrid L0/L1 topology through the control plane."""

import shutil
import subprocess
from pathlib import Path

import pytest

from polmon.api.control import ControlPlane

TOPOLOGY = Path(__file__).parents[2] / "examples/topologies/hybrid-tap.yml"
SCENARIO = """id: hybrid-recon
required_topology: hybrid-tap
initial_conditions: [topology_deployed]
permitted_actions: [icmp_probe]
sequence:
  - id: l0-reaches-l1
    kind: icmp_probe
    source: synthetic
    target: linux
  - id: l1-reaches-l0
    kind: icmp_probe
    source: linux
    target: synthetic
timeout_seconds: 20
success_conditions:
  - action: l0-reaches-l1
    field: success
    equals: true
  - action: l1-reaches-l0
    field: detail
    equals: unsupported
cleanup_policy: never
"""


def hybrid_available() -> bool:
    if any(shutil.which(tool) is None for tool in ("ip", "sudo", "setpriv")):
        return False
    if not Path("/dev/net/tun").exists():
        return False
    result = subprocess.run(
        ["sudo", "-n", "ip", "netns", "list"], capture_output=True, check=False, timeout=3
    )
    return result.returncode == 0


@pytest.mark.integration
@pytest.mark.privileged
def test_hybrid_experiment_captures_reports_and_resets(tmp_path) -> None:
    if not hybrid_available():
        pytest.skip("NOT RUN — environment unavailable: TAP and namespace privileges required")
    plane = ControlPlane(tmp_path)
    topology_id = str(plane.load_topology(TOPOLOGY.read_text(encoding="utf-8"))["topology_id"])
    try:
        deployment = plane.deploy(topology_id)
        tap = next(item for item in deployment["resources"] if item.startswith("tap:"))
        result = plane.run_experiment("hybrid-one", topology_id, SCENARIO)
        assert result["status"] == "succeeded", result
        observations = {item["action_id"]: item for item in result["observations"]}
        assert observations["l0-reaches-l1"]["data"]["path"] == "l0->l1"
        assert observations["l1-reaches-l0"]["detail"] == "unsupported"
        assert result["capture"]["frame_count"] >= 4  # ARP request/reply + ICMP request/reply
        pcap = Path(result["capture"]["path"])
        assert pcap.is_file() and pcap.stat().st_size > 24
        report = plane.experiment_report("hybrid-one")
        assert report["status"] == "succeeded" and report["experiment_id"] == "hybrid-one"
        assert Path(result["reports"]["markdown"]).is_file()
        assert plane.reset_all()["deployments_destroyed"] == 1
    finally:
        plane.reset_all()
    links = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True).stdout
    assert tap.split(":", 1)[1] not in links
