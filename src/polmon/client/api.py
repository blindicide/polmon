"""Timeout-bound standard-library HTTP client used by the Qt desktop client and the demo."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn


class ApiClientError(RuntimeError):
    """A failed call; ``status``/``code``/``message_code``/``params``/``details`` mirror the
    backend's error document (``message_code`` is absent from backends before v0.4.0)."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        details: object = None,
        message_code: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details
        self.message_code = message_code
        self.params = params or {}


DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 5.0
DEPLOY_TIMEOUT = 30.0
EXPERIMENT_TIMEOUT = 120.0


class ApiClient:
    def __init__(
        self, base_url: str, *, timeout: float = DEFAULT_TIMEOUT, token: str | None = None
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("server URL must be absolute HTTP(S)")
        if not 0 < timeout <= 600:
            raise ValueError("timeout must be between 0 and 600 seconds")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or None

    @property
    def has_token(self) -> bool:
        return self._token is not None

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
                body = response.read()
        except urllib.error.HTTPError as error:
            self._raise_http(error)
        except (urllib.error.URLError, TimeoutError) as error:
            reason = error.reason if hasattr(error, "reason") else error
            raise ApiClientError(f"unable to reach backend: {reason}") from error
        except OSError as error:  # e.g. connection reset/aborted mid-request (WinError 10053)
            raise ApiClientError(f"connection to backend failed: {error}") from error
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiClientError(
                "backend returned a malformed response (not JSON); is this a polmon backend?",
                code="malformed_response",
            ) from error

    def _bytes(self, path: str, *, limit: int) -> bytes:
        """GET a binary resource of at most ``limit`` bytes (errors as in ``_request``)."""
        request = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={**({"Authorization": f"Bearer {self._token}"} if self._token else {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            self._raise_http(error)
        except (urllib.error.URLError, TimeoutError) as error:
            reason = error.reason if hasattr(error, "reason") else error
            raise ApiClientError(f"unable to reach backend: {reason}") from error
        except OSError as error:
            raise ApiClientError(f"connection to backend failed: {error}") from error
        if len(body) > limit:
            raise ApiClientError(
                f"download exceeds the {limit}-byte client limit",
                code="download_too_large",
                params={"limit": limit},
            )
        return body

    def _dict(self, method: str, path: str, payload=None, *, timeout=None) -> dict[str, object]:
        document = self._request(method, path, payload, timeout=timeout)
        if not isinstance(document, dict):
            raise ApiClientError(
                f"backend returned an unexpected response for {path} (expected an object)",
                code="malformed_response",
            )
        return document

    def _list(self, path: str) -> list[dict[str, object]]:
        document = self._request("GET", path)
        if not isinstance(document, list) or not all(isinstance(item, dict) for item in document):
            raise ApiClientError(
                f"backend returned an unexpected response for {path} (expected a list)",
                code="malformed_response",
            )
        return document

    @staticmethod
    def _raise_http(error: urllib.error.HTTPError) -> NoReturn:
        """Raise the backend's error document (or the HTTP reason) as ``ApiClientError``."""
        try:
            document = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            document = None
        body = document.get("error") if isinstance(document, dict) else None
        message_code: str | None = None
        params: dict[str, object] = {}
        if isinstance(body, dict):
            code = str(body.get("code") or "error")
            message = str(body.get("message") or error.reason)
            details = body.get("details")
            if isinstance(body.get("message_code"), str):
                message_code = str(body["message_code"])
            if isinstance(body.get("params"), dict):
                params = dict(body["params"])
        else:
            code, message, details = None, str(error.reason), document
        raise ApiClientError(
            f"server returned HTTP {error.code}"
            + (f" {code}" if code else "")
            + f": {message}",
            status=error.code,
            code=code,
            details=details,
            message_code=message_code,
            params=params,
        ) from error

    def health(self) -> dict[str, object]:
        return self._dict("GET", "/v1/health")

    def validate_topology(self, source: str) -> dict[str, object]:
        return self._dict("POST", "/v1/topologies/validate", {"yaml": source})

    def load_topology(self, source: str) -> dict[str, object]:
        return self._dict("POST", "/v1/topologies", {"yaml": source})

    def save_topology(self, topology_id: str, source: str) -> dict[str, object]:
        return self._dict(
            "PUT", f"/v1/topologies/{_segment(topology_id)}", {"yaml": source}
        )

    def topologies(self) -> list[dict[str, object]]:
        return self._list("/v1/topologies")

    def topology(self, topology_id: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/topologies/{_segment(topology_id)}")

    def unload_topology(self, topology_id: str) -> dict[str, object]:
        return self._dict("DELETE", f"/v1/topologies/{_segment(topology_id)}")

    def validate_scenario(self, source: str) -> dict[str, object]:
        return self._dict("POST", "/v1/scenarios/validate", {"yaml": source})

    def deploy(self, topology_id: str) -> dict[str, object]:
        path = f"/v1/deployments/{_segment(topology_id)}"
        return self._dict("POST", path, timeout=max(DEPLOY_TIMEOUT, self.timeout))

    def deployment(self, topology_id: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/deployments/{_segment(topology_id)}")

    def destroy(self, topology_id: str) -> dict[str, object]:
        path = f"/v1/deployments/{_segment(topology_id)}"
        return self._dict("DELETE", path, timeout=max(DEPLOY_TIMEOUT, self.timeout))

    def reset_all(self) -> dict[str, object]:
        return self._dict("POST", "/v1/reset", timeout=max(DEPLOY_TIMEOUT, self.timeout))

    def resources(self) -> dict[str, object]:
        return self._dict("GET", "/v1/resources")

    def run_experiment(
        self, experiment_id: str, topology_id: str, scenario_source: str, *, wait: bool = True
    ) -> dict[str, object]:
        """Run an experiment; ``wait=False`` returns once admitted (poll ``experiment``)."""
        return self._dict(
            "POST",
            "/v1/experiments",
            {
                "experiment_id": experiment_id,
                "topology_id": topology_id,
                "scenario_yaml": scenario_source,
                "wait": wait,
            },
            timeout=max(EXPERIMENT_TIMEOUT, self.timeout) if wait else None,
        )

    def experiment(self, experiment_id: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/experiments/{_segment(experiment_id)}")

    def experiments(self, limit: int = 200) -> list[dict[str, object]]:
        return self._list(f"/v1/experiments?limit={int(limit)}")

    def telemetry(
        self, experiment_id: str, *, after: int = 0, limit: int | None = None
    ) -> list[dict[str, object]]:
        query = {"after": int(after), **({"limit": int(limit)} if limit else {})}
        path = f"/v1/experiments/{_segment(experiment_id)}/telemetry"
        return self._list(f"{path}?{urllib.parse.urlencode(query)}")

    def report(self, experiment_id: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/experiments/{_segment(experiment_id)}/report")

    def report_markdown(self, experiment_id: str) -> str:
        path = f"/v1/experiments/{_segment(experiment_id)}/report/markdown"
        markdown = self._dict("GET", path).get("markdown")
        if not isinstance(markdown, str):
            raise ApiClientError("backend report has no Markdown text", code="malformed_response")
        return markdown

    def capture(self, experiment_id: str, *, limit: int = 1_073_741_824) -> bytes:
        """The experiment's PCAP capture (bounded by the backend's capture limit)."""
        return self._bytes(f"/v1/experiments/{_segment(experiment_id)}/capture", limit=limit)

    def cancel_experiment(self, experiment_id: str) -> dict[str, object]:
        return self._dict("POST", f"/v1/experiments/{_segment(experiment_id)}/cancel")

    def start_benchmark(self, request: dict[str, object]) -> dict[str, object]:
        return self._dict("POST", "/v1/benchmarks", request)

    def benchmark_job(self, job_id: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/benchmarks/jobs/{_segment(job_id)}")

    def benchmark_jobs(self) -> list[dict[str, object]]:
        return self._list("/v1/benchmarks/jobs")

    def cancel_benchmark(self, job_id: str) -> dict[str, object]:
        return self._dict("POST", f"/v1/benchmarks/jobs/{_segment(job_id)}/cancel")

    def benchmark_results(self) -> list[dict[str, object]]:
        return self._list("/v1/benchmarks/results")

    def benchmark_result(self, name: str) -> dict[str, object]:
        return self._dict("GET", f"/v1/benchmarks/results/{_segment(name)}")


def _segment(value: str) -> str:
    """Quote one path segment so identifiers can never change the request path."""
    return urllib.parse.quote(value, safe="")
