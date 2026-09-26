"""Timeout-bound standard-library HTTP client used by the Windows GUI."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import TypeVar, cast

T = TypeVar("T")


class ApiClientError(RuntimeError):
    """A failed call; ``status``/``code``/``details`` mirror the backend's error document."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        details: object = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class ApiClient:
    def __init__(
        self, base_url: str, *, timeout: float = 5.0, token: str | None = None
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("server URL must be absolute HTTP(S)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or None

    def __repr__(self) -> str:  # never reveal the token in logs or tracebacks
        return f"ApiClient({self.base_url!r}, token={'set' if self._token else 'unset'})"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float | None = None,
    ) -> object:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                **({"Authorization": f"Bearer {self._token}"} if self._token else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                document = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                document = None
            body = document.get("error") if isinstance(document, dict) else None
            if isinstance(body, dict):
                code = str(body.get("code") or "error")
                message = str(body.get("message") or error.reason)
                details = body.get("details")
            else:
                code, message, details = None, str(error.reason), document
            raise ApiClientError(
                f"server returned HTTP {error.code}"
                + (f" {code}" if code else "")
                + f": {message}",
                status=error.code,
                code=code,
                details=details,
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            reason = error.reason if hasattr(error, "reason") else error
            raise ApiClientError(f"unable to reach backend: {reason}") from error
        except OSError as error:  # e.g. connection reset/aborted mid-request (WinError 10053)
            raise ApiClientError(f"connection to backend failed: {error}") from error

    def health(self) -> dict[str, object]:
        return cast(dict[str, object], self._request("GET", "/v1/health"))

    def validate_topology(self, source: str) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._request("POST", "/v1/topologies/validate", {"yaml": source}),
        )

    def load_topology(self, source: str) -> dict[str, object]:
        return cast(
            dict[str, object], self._request("POST", "/v1/topologies", {"yaml": source})
        )

    def deploy(self, topology_id: str) -> dict[str, object]:
        safe = urllib.parse.quote(topology_id, safe="")
        return cast(
            dict[str, object],
            self._request("POST", f"/v1/deployments/{safe}", timeout=30),
        )

    def destroy(self, topology_id: str) -> dict[str, object]:
        safe = urllib.parse.quote(topology_id, safe="")
        return cast(
            dict[str, object],
            self._request("DELETE", f"/v1/deployments/{safe}", timeout=30),
        )

    def reset_all(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._request("POST", "/v1/reset", timeout=30),
        )

    def resources(self) -> dict[str, object]:
        return cast(dict[str, object], self._request("GET", "/v1/resources"))

    def run_experiment(
        self, experiment_id: str, topology_id: str, scenario_source: str
    ) -> dict[str, object]:
        return cast(
            dict[str, object],
            self._request(
                "POST",
                "/v1/experiments",
                {
                    "experiment_id": experiment_id,
                    "topology_id": topology_id,
                    "scenario_yaml": scenario_source,
                },
                timeout=120,
            ),
        )

    def telemetry(self, experiment_id: str) -> list[dict[str, object]]:
        safe = urllib.parse.quote(experiment_id, safe="")
        return cast(
            list[dict[str, object]],
            self._request("GET", f"/v1/experiments/{safe}/telemetry"),
        )

    def report(self, experiment_id: str) -> dict[str, object]:
        safe = urllib.parse.quote(experiment_id, safe="")
        return cast(
            dict[str, object],
            self._request("GET", f"/v1/experiments/{safe}/report"),
        )

    def cancel_experiment(self, experiment_id: str) -> dict[str, object]:
        safe = urllib.parse.quote(experiment_id, safe="")
        return cast(
            dict[str, object],
            self._request("POST", f"/v1/experiments/{safe}/cancel"),
        )
