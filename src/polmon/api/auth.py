"""Optional bearer-token authentication for the HTTP API (fails closed off loopback)."""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import stat
from pathlib import Path

from polmon.api.limits import ASGIApp, Receive, Scope, Send
from polmon.core.errors import ConfigurationError

TOKEN_ENVIRONMENT_VARIABLE = "POLMON_API_TOKEN"
MIN_TOKEN_LENGTH = 24
# Liveness stays readable without a token so clients can report "reachable, unauthorised".
PUBLIC_PATHS = frozenset({"/", "/v1/health"})


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_token_file(path: Path) -> str:
    """Read a token from a file only its owner can access (POSIX permission check)."""
    if os.name == "posix":
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ConfigurationError(
                f"API token file {path} must not be accessible to group or others (chmod 600)"
            )
    return path.read_text(encoding="utf-8").strip()


def resolve_token(token_file: Path | None, environment: dict[str, str] | None = None) -> str | None:
    environment = dict(os.environ) if environment is None else environment
    token = read_token_file(token_file) if token_file is not None else None
    token = token or environment.get(TOKEN_ENVIRONMENT_VARIABLE) or None
    if token is not None and len(token) < MIN_TOKEN_LENGTH:
        raise ConfigurationError(f"API token must be at least {MIN_TOKEN_LENGTH} characters")
    return token


def require_safe_binding(host: str, token: str | None) -> None:
    if token is None and not is_loopback(host):
        raise ConfigurationError(
            f"refusing to listen on {host} without an API token; set "
            f"{TOKEN_ENVIRONMENT_VARIABLE} or --api-token-file, or bind to 127.0.0.1"
        )


class BearerTokenAuth:
    """Require ``Authorization: Bearer <token>`` on every non-public HTTP path."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
        if hmac.compare_digest(supplied, self._expected):
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {
                "error": {
                    "code": "unauthorized",
                    "message": "a valid API token is required",
                    "details": {},
                }
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
