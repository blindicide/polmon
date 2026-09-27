"""Backend errors carry stable message codes a client can render in its own language."""

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.core.errors import CodedValueError, PolmonError

SOURCE = Path(__file__).parents[2] / "src/polmon"
CODED_EXCEPTIONS = {
    "PolmonError",
    "ConfigurationError",
    "ResourceLimitError",
    "OrchestrationError",
    "ScenarioError",
    "SyntheticEngineError",
    "PacketError",
    "BenchmarkLimitError",
}
VALIDATOR_MODULES = ("topology/models.py", "scenarios/models.py")


def backend_modules() -> list[Path]:
    return [path for path in SOURCE.rglob("*.py") if "client" not in path.parts]


def test_every_backend_error_raise_names_a_message_code() -> None:
    uncoded = []
    for path in backend_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            call = node.exc if isinstance(node, ast.Raise) else None
            if not isinstance(call, ast.Call):
                continue
            name = ast.unparse(call.func).rsplit(".", 1)[-1]
            if name in CODED_EXCEPTIONS:
                keywords = {keyword.arg for keyword in call.keywords}
                if "message_code" not in keywords:
                    uncoded.append(f"{path.relative_to(SOURCE)}:{node.lineno} {name}")
            elif name == "CodedValueError" and len(call.args) < 2:
                uncoded.append(f"{path.relative_to(SOURCE)}:{node.lineno} CodedValueError")
    assert uncoded == []


def test_model_validators_raise_only_coded_value_errors() -> None:
    plain = []
    for relative in VALIDATOR_MODULES:
        path = SOURCE / relative
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and ast.unparse(node.exc.func) == "ValueError"
            ):
                plain.append(f"{relative}:{node.lineno}")
    assert plain == []


def test_error_documents_carry_code_params_and_the_english_message(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path, l0_only=True)))
    missing = client.get("/v1/experiments/nope/report").json()["error"]
    assert missing["message_code"] == "experiment.report_missing"
    assert missing["params"] == {"experiment_id": "nope"}
    assert missing["message"] == "report for experiment 'nope' does not exist"

    invalid = client.post("/v1/topologies/validate", json={"yaml": "id: Bad\nnetworks: []"})
    error = invalid.json()["error"]
    assert error["message_code"] == "topology.validation_failed"
    codes = {item["location"]: item["message_code"] for item in error["details"]["errors"]}
    assert codes["id"] == "topology.identifier_format"
    assert codes["nodes"] == "pydantic.missing"

    broken = client.post("/v1/topologies/validate", json={"yaml": "a: b: c"}).json()["error"]
    assert broken["message_code"] == "topology.yaml_invalid"
    assert broken["params"] == {"line": 1, "column": 5}
    assert broken["details"]["problem_code"] == "mapping_values_not_allowed"


def test_coded_errors_keep_json_safe_parameters() -> None:
    error = PolmonError("x", message_code="t.x", params={"items": ["a", "b"], "path": Path("/p")})
    assert error.params == {"items": "a, b", "path": str(Path("/p"))}
    assert CodedValueError("x", "t.y", n=3).params == {"n": 3}
