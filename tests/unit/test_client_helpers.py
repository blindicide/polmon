"""Qt-free client helpers: error mapping, formatting, YAML error locations.

Assertions use identifiers (problem keys, backend message codes, limit names) — never display
text — so they hold in every UI language.
"""

import pytest

from polmon.client import i18n
from polmon.client.api import ApiClientError
from polmon.client.errors import describe, limit_items
from polmon.client.formatting import (
    estimate_eta,
    format_bytes,
    format_seconds,
    progress_text,
)
from polmon.client.i18n import Msg
from polmon.client.yamlmap import document_id, locate, reason_line

LANGUAGES = i18n.languages()


@pytest.fixture(params=LANGUAGES)
def language(request):  # noqa: ANN001, ANN201
    previous = i18n.language()
    i18n.set_language(request.param)
    yield request.param
    i18n.set_language(previous)


def test_admission_rejections_list_every_limit(language) -> None:  # noqa: ANN001
    error = ApiClientError(
        "server returned HTTP 429 resource_limit: topology exceeds configured resource limits",
        status=429,
        code="resource_limit",
        message_code="admission.topology_limits",
        details={
            "endpoint_count": {"projected": 300, "limit": 250},
            "available_memory": {"required_mb_including_reserve": 900, "available_mb": 512},
        },
    )
    problem = describe(error)
    assert problem.key == "problem.admission"
    assert problem.message_code == "admission.topology_limits"
    assert isinstance(problem.detail_message, Msg)
    assert problem.detail_message.key == "backend.admission.topology_limits"
    assert [item.name for item in problem.item_messages] == ["endpoint_count", "available_memory"]
    rendered = problem.text()
    assert "300" in rendered and "250" in rendered and "900" in rendered and "512" in rendered
    assert "Traceback" not in rendered and not i18n.missing


def test_transport_failures_are_actionable(language) -> None:  # noqa: ANN001
    refused = describe(
        ApiClientError("unable to reach backend: [Errno 111] Connection refused"),
        url="http://10.0.0.5:8080",
    )
    assert refused.key == "problem.refused" and "10.0.0.5" in refused.detail
    assert refused.hint and "polmon-backend" in refused.hint
    windows_refused = describe(ApiClientError("unable to reach backend: [WinError 10061] ..."))
    assert windows_refused.key == "problem.refused"
    slow = describe(ApiClientError("unable to reach backend: timed out"), timeout=5)
    assert slow.key == "problem.timeout" and slow.detail_message.params["seconds"] == "5"
    reset = describe(ApiClientError("connection to backend failed: [Errno 104] reset by peer"))
    assert reset.key == "problem.dropped"
    assert not i18n.missing


def test_http_errors_map_to_problem_keys(language) -> None:  # noqa: ANN001
    unauthorized = describe(ApiClientError("x", status=401, code="unauthorized"))
    assert unauthorized.key == "problem.unauthorized"
    invalid = describe(
        ApiClientError(
            "server returned HTTP 422 configuration_error: topology validation failed",
            status=422,
            code="configuration_error",
            message_code="topology.validation_failed",
            details={
                "errors": [
                    {
                        "location": "nodes.0.id",
                        "message": "bad id",
                        "message_code": "topology.identifier_format",
                        "params": {},
                    }
                ]
            },
        )
    )
    assert invalid.key == "problem.rejected"
    assert invalid.detail_message.key == "backend.topology.validation_failed"
    (item,) = invalid.item_messages
    assert item.location == "nodes.0.id"
    assert item.message.key == "backend.topology.identifier_format"
    refused = describe(
        ApiClientError(
            "x", status=422, code="configuration_error", message_code="fidelity.l0_only"
        )
    )
    assert refused.key == "problem.l0_only" and refused.message_code == "fidelity.l0_only"
    assert describe(ApiClientError("x", status=404)).key == "problem.unsupported"
    assert describe(ApiClientError("x", status=503)).key == "problem.server"
    malformed = describe(ApiClientError("backend returned junk", code="malformed_response"))
    assert malformed.key == "problem.malformed"
    assert describe(ValueError("server URL must be absolute HTTP(S)")).key == "problem.settings"
    unexpected = describe(RuntimeError("boom"))
    assert unexpected.key == "problem.unexpected" and "RuntimeError" in unexpected.detail
    assert limit_items("not a dict") == ()
    assert not i18n.missing


def test_uncoded_backend_text_is_quoted_inside_a_localized_sentence(language) -> None:  # noqa: ANN001
    older = describe(
        ApiClientError(
            "server returned HTTP 422 configuration_error: something old",
            status=422,
            code="configuration_error",
        )
    )
    assert older.detail_message.key == "backend.uncoded"
    assert "something old" in older.detail


def test_formatting_is_compact_and_total(language) -> None:  # noqa: ANN001
    assert format_bytes(512) == "512 B"
    assert format_bytes(3 * 1_048_576) == "3.0 MiB"
    assert format_bytes(None) == "—"
    assert format_seconds(0.25) == "250 ms"  # unit symbols are the same in every language
    assert format_seconds(75) == "1 min 15 s"
    assert format_seconds(3700) == "1 h 01 min"
    assert estimate_eta(2, 10, 4.0) == 16.0
    assert estimate_eta(0, 10, 4.0) is None
    text = progress_text(3, 10, 4.2, 9.8, "action ping")
    parts = text.split(" · ")
    assert "3/10" in parts[0] and parts[1] == "30 %" and parts[-1] == "action ping"
    assert "4.2 s" in parts[2] and "9.8 s" in parts[3]


def test_yaml_locations_resolve_to_lines() -> None:
    source = "id: t\nnetworks:\n  - id: lab\n    ipv4_subnet: 8.8.8.0/24\nnodes: []\n"
    assert locate(source, "networks.0.ipv4_subnet") == 4
    assert locate(source, "networks.0.missing") == 3  # closest ancestor
    assert locate(source, "nodes") == 5
    message = 'while parsing a block mapping\n  in "<unicode string>", line 7, column 3'
    assert reason_line(message) == 7
    assert document_id(source) == "t"
    assert document_id(": not yaml : [") is None
