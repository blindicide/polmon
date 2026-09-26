import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from polmon.api.auth import (
    MIN_TOKEN_LENGTH,
    TOKEN_ENVIRONMENT_VARIABLE,
    is_loopback,
    require_safe_binding,
    resolve_token,
)
from polmon.api.control import ControlPlane
from polmon.backend import create_app
from polmon.client.api import ApiClient
from polmon.core.errors import ConfigurationError

TOKEN = "t" * MIN_TOKEN_LENGTH


def test_token_is_required_on_every_non_public_path(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path), api_token=TOKEN))
    assert client.get("/v1/health").status_code == 200  # liveness stays public
    assert client.get("/").status_code == 200
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
        response = client.get("/v1/resources", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"
    rejected = client.post("/v1/reset", headers={"Authorization": "Bearer nope"})
    assert rejected.status_code == 401
    ok = client.get("/v1/resources", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200


def test_unauthenticated_oversized_bodies_are_refused_without_buffering(tmp_path) -> None:
    client = TestClient(create_app(ControlPlane(tmp_path), api_token=TOKEN))
    response = client.post("/v1/topologies", content=b" " * (6 * 1_048_576))
    assert response.status_code == 401  # auth runs before the body is read


def test_token_resolution_and_file_permissions(tmp_path) -> None:
    assert resolve_token(None, {}) is None
    assert resolve_token(None, {TOKEN_ENVIRONMENT_VARIABLE: TOKEN}) == TOKEN
    with pytest.raises(ConfigurationError, match="at least"):
        resolve_token(None, {TOKEN_ENVIRONMENT_VARIABLE: "short"})
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    token_file.chmod(0o600)
    assert resolve_token(token_file, {}) == TOKEN
    if os.name == "posix":
        token_file.chmod(0o644)
        with pytest.raises(ConfigurationError, match="chmod 600"):
            resolve_token(token_file, {})


def test_non_loopback_binding_requires_a_token() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("10.0.0.5")
    require_safe_binding("127.0.0.1", None)
    require_safe_binding("0.0.0.0", TOKEN)
    with pytest.raises(ConfigurationError, match="refusing to listen"):
        require_safe_binding("0.0.0.0", None)


def test_backend_refuses_to_start_exposed_without_a_token() -> None:
    environment = {key: value for key, value in os.environ.items()}
    environment.pop(TOKEN_ENVIRONMENT_VARIABLE, None)
    result = subprocess.run(
        [sys.executable, "-m", "polmon.backend", "--host", "0.0.0.0", "--port", "9"],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert result.returncode != 0
    assert "refusing to listen on 0.0.0.0 without an API token" in result.stderr


def test_client_repr_never_reveals_the_token() -> None:
    client = ApiClient("http://127.0.0.1:1", token=TOKEN)
    assert TOKEN not in repr(client) and "token=set" in repr(client)


def test_client_authenticates_against_a_live_backend(tmp_path) -> None:
    import socket
    import threading

    import uvicorn

    from polmon.client.api import ApiClientError

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(ControlPlane(tmp_path), api_token=TOKEN),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        anonymous = ApiClient(f"http://127.0.0.1:{port}", timeout=2)
        for _ in range(100):
            try:
                anonymous.health()
                break
            except ApiClientError:
                threading.Event().wait(0.05)
        with pytest.raises(ApiClientError) as refused:
            anonymous.resources()
        assert refused.value.status == 401 and refused.value.code == "unauthorized"
        authorised = ApiClient(f"http://127.0.0.1:{port}", timeout=2, token=TOKEN)
        assert authorised.resources()["active_deployments"] == 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
