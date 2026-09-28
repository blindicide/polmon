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
    assert "outside address space" in json.dumps(error)


def test_topology_cli_migrates_legacy_file_in_place(capsys, tmp_path) -> None:
    legacy = tmp_path / "legacy.yml"
    legacy.write_text(
        "id: old\nnetworks: [{id: lab, ipv4_subnet: 10.20.0.0/24}]\nnodes: []\n",
        encoding="utf-8",
    )
    assert cli.main(["--migrate", str(legacy)]) == 0
    assert json.loads(capsys.readouterr().out)["migrated"] is True
    migrated = legacy.read_text(encoding="utf-8")
    assert "address_space: lab-profile" in migrated
    assert "192.168.230.0/24" in migrated
