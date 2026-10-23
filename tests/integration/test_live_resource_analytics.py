"""Live service attribution; the privileged wrapper also proves host invariance."""

import json
import time
from pathlib import Path

import pytest

from polmon.api.control import ControlPlane
from polmon.resources import ResourceLimits
from tests.integration.test_namespace_networking import namespace_available


@pytest.mark.privileged
@pytest.mark.integration
def test_live_namespace_resource_attribution(tmp_path):
    if not namespace_available():
        pytest.skip("NOT RUN — environment unavailable: namespace privileges")
    plane = ControlPlane(tmp_path, limits=ResourceLimits(analytics_interval_seconds=0.25))
    source = (Path(__file__).parents[2] / "examples/topologies/l1-two-node.yml").read_text()
    topology = plane.load_topology(source)
    topology_id = topology["topology_id"]
    try:
        plane.deploy(topology_id)
        backend = plane.deployments[topology_id].backend
        for _ in range(30):
            if backend.probe_tcp("client", "192.168.236.20", 8080):
                break
            time.sleep(0.1)
        else:
            pytest.fail("HTTP service failed to become ready")
        plane.resource_history()
        time.sleep(0.3)
        history = plane.resource_history()
        sample = history["samples"][-1]
        server = next(row for row in sample["nodes"] if row["node_id"] == "server")
        assert server["rss_bytes"] > 0
        assert server["process_count"] >= 1
        assert server["cpu_seconds"] >= 0
        assert server["node_uuid"] == str(plane.topologies[topology_id].nodes[1].uuid)
        # Restricted procfs may make network/I/O counters unavailable: never replace with zeros.
        print("RESOURCE-ANALYTICS-EVIDENCE " + json.dumps(history, sort_keys=True))
    finally:
        plane.shutdown()
        plane.close()
    assert not backend.inspect().resources
