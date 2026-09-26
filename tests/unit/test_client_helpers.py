"""Qt-free client helpers: error mapping, formatting, YAML error locations."""

from polmon.client.api import ApiClientError
from polmon.client.errors import describe, limit_items
from polmon.client.formatting import (
    estimate_eta,
    format_bytes,
    format_seconds,
    progress_text,
)
from polmon.client.yamlmap import document_id, locate, reason_line


def test_admission_rejections_list_every_limit() -> None:
    error = ApiClientError(
        "server returned HTTP 429 resource_limit: topology exceeds configured resource limits",
        status=429,
        code="resource_limit",
        details={
            "endpoint_count": {"projected": 300, "limit": 250},
            "available_memory": {"required_mb_including_reserve": 900, "available_mb": 512},
        },
    )
    problem = describe(error)
    assert problem.title == "Refused by admission control"
    assert problem.detail == "topology exceeds configured resource limits"
    assert problem.items == (
        "Endpoints: projected 300, limit 250",
        "Available memory: required mb including reserve 900, available mb 512",
    )
    assert "Traceback" not in problem.text()


def test_transport_failures_are_actionable() -> None:
    refused = describe(
        ApiClientError("unable to reach backend: [Errno 111] Connection refused"),
        url="http://10.0.0.5:8080",
    )
    assert refused.title == "Backend unreachable" and "10.0.0.5" in refused.detail
    assert "polmon-backend" in refused.hint
    windows_refused = describe(ApiClientError("unable to reach backend: [WinError 10061] ..."))
    assert windows_refused.title == "Backend unreachable"
    slow = describe(ApiClientError("unable to reach backend: timed out"), timeout=5)
    assert slow.title == "Backend did not respond" and "5 s" in slow.detail
    reset = describe(ApiClientError("connection to backend failed: [Errno 104] reset by peer"))
    assert reset.title == "Connection dropped"


def test_http_errors_map_to_operator_language() -> None:
    unauthorized = describe(ApiClientError("x", status=401, code="unauthorized"))
    assert unauthorized.title == "API token required"
    invalid = describe(
        ApiClientError(
            "server returned HTTP 422 configuration_error: topology validation failed",
            status=422,
            code="configuration_error",
            details={"errors": [{"location": "nodes.0.id", "message": "bad id"}]},
        )
    )
    assert invalid.detail == "topology validation failed"
    assert invalid.items == ("nodes.0.id: bad id",)
    assert describe(ApiClientError("x", status=404)).title == "Not supported by this backend"
    assert describe(ApiClientError("x", status=503)).title == "Backend error"
    malformed = describe(ApiClientError("backend returned junk", code="malformed_response"))
    assert malformed.title == "Unexpected response"
    assert describe(ValueError("server URL must be absolute HTTP(S)")).title == "Invalid settings"
    assert describe(RuntimeError("boom")).detail == "RuntimeError: boom"
    assert limit_items("not a dict") == ()


def test_formatting_is_compact_and_total() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(3 * 1_048_576) == "3.0 MiB"
    assert format_bytes(None) == "—"
    assert format_seconds(0.25) == "250 ms"
    assert format_seconds(75) == "1m 15s"
    assert estimate_eta(2, 10, 4.0) == 16.0
    assert estimate_eta(0, 10, 4.0) is None
    assert progress_text(3, 10, 4.2, 9.8, "action ping") == (
        "step 3/10 · 30 % · 4.2 s elapsed · ETA 9.8 s · action ping"
    )


def test_yaml_locations_resolve_to_lines() -> None:
    source = "id: t\nnetworks:\n  - id: lab\n    ipv4_subnet: 8.8.8.0/24\nnodes: []\n"
    assert locate(source, "networks.0.ipv4_subnet") == 4
    assert locate(source, "networks.0.missing") == 3  # closest ancestor
    assert locate(source, "nodes") == 5
    message = 'while parsing a block mapping\n  in "<unicode string>", line 7, column 3'
    assert reason_line(message) == 7
    assert document_id(source) == "t"
    assert document_id(": not yaml : [") is None
