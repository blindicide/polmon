"""Gate classification must distinguish real passes from skipped/unavailable runs."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "vm_gate", Path(__file__).parents[2] / "scripts/vm-gate.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("prefix", ["", "tests/integration/test_vm_guest.py "])
def test_evidence_is_retained_with_pytest_progress_prefix(prefix):
    log = prefix + 'REAL-VM-EVIDENCE {"mode": "userns", "sample": {"nodes": {}}}\n.\n'
    assert gate.evidence_lines(log) == [{"mode": "userns", "sample": {"nodes": {}}}]


@pytest.mark.parametrize(
    ("junit", "code", "expected"),
    [
        ('<testsuite tests="1"/>', 0, "PASS"),
        ('<testsuites><testsuite tests="1"/></testsuites>', 0, "PASS"),
        ('<testsuite tests="1" skipped="1"/>', 0, "NOT_RUN"),
        ('<testsuite tests="0"/>', 5, "NOT_RUN"),
        (None, 2, "NOT_RUN"),
        (None, 0, "FAIL"),
        ('<testsuite tests="1" failures="1"/>', 1, "FAIL"),
        ('<testsuite tests="1" errors="1"/>', 1, "FAIL"),
        ('<testsuite tests="1"/>', 1, "FAIL"),
    ],
)
def test_gate_classifies_results_without_waiving_failures(junit, code, expected):
    assert gate.classify(junit, code)[0] == expected


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS", "PASS"], "PASS"),
        (["PASS", "NOT_RUN"], "NOT_RUN"),
        (["FAIL", "NOT_RUN"], "FAIL"),
        ([], "NOT_RUN"),
    ],
)
def test_all_requested_modes_must_pass(statuses, expected):
    assert gate.overall(statuses) == expected
