import json
from pathlib import Path

from polmon.topology import cli
from polmon.version import __version__

EXAMPLE = Path(__file__).parents[2] / "examples/topologies/mvp-demo.yml"


def test_topology_cli_reports_estimates_as_json(capsys) -> None:
    assert cli.main([str(EXAMPLE), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["version"] == __version__ and result["topology"] == "mvp-demo"
    assert result["resources"]["l0_endpoints"] == 50
    assert result["resources"]["l1_namespaces"] == 2


def test_topology_cli_prints_normalized_yaml_that_round_trips(capsys, tmp_path) -> None:
    assert cli.main([str(EXAMPLE), "--normalized"]) == 0
    normalized = tmp_path / "normalized.yml"
    normalized.write_text(capsys.readouterr().out, encoding="utf-8")
    assert cli.main([str(normalized), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["topology"] == "mvp-demo"


def test_topology_cli_explains_invalid_files_on_stderr(capsys, tmp_path) -> None:
    broken = tmp_path / "broken.yml"
    broken.write_text("id: outside\nnetworks:\n  - {id: lab, ipv4_subnet: 8.8.8.0/24}\nnodes: []\n")
    assert cli.main([str(broken)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"] == "configuration_error"
    assert "controlled laboratory ranges" in json.dumps(error)
