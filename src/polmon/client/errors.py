"""Turn any client-side failure into a short, actionable operator message (never a traceback)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from polmon.client.api import ApiClientError

# Human labels for the violation keys the backend's admission control reports.
LIMIT_LABELS = {
    "endpoint_count": "Endpoints",
    "active_namespaces": "Active namespaces",
    "available_memory": "Available memory",
    "concurrent_experiments": "Concurrent experiments",
    "duration_seconds": "Experiment duration (s)",
    "data_directory": "Data directory",
    "disk_free": "Free disk",
    "max_endpoints": "Benchmark max endpoints",
    "max_namespaces": "Benchmark max namespaces",
    "memory_reserve_mb": "Benchmark memory reserve (MiB)",
    "max_run_seconds": "Benchmark run time (s)",
    "concurrent_benchmarks": "Concurrent benchmarks",
    "active_experiments": "Active experiments",
    "benchmark_jobs": "Running benchmark jobs",
}


@dataclass(frozen=True, slots=True)
class Problem:
    """What went wrong (``title``), the specifics (``detail``/``items``) and what to do."""

    title: str
    detail: str
    hint: str | None = None
    items: tuple[str, ...] = field(default_factory=tuple)
    status: int | None = None
    code: str | None = None

    def text(self) -> str:
        lines = [f"{self.title}: {self.detail}"]
        lines += [f"  • {item}" for item in self.items]
        if self.hint:
            lines.append(self.hint)
        return "\n".join(lines)


def _pairs(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key.replace('_', ' ')} {item}" for key, item in value.items())
    return str(value)


def limit_items(details: object) -> tuple[str, ...]:
    """One line per violated limit, e.g. ``Endpoints: projected 300, limit 250``."""
    if not isinstance(details, dict):
        return ()
    return tuple(
        f"{LIMIT_LABELS.get(key, key.replace('_', ' '))}: {_pairs(value)}"
        for key, value in details.items()
    )


def validation_items(details: object) -> tuple[str, ...]:
    if not isinstance(details, dict):
        return ()
    errors = details.get("errors")
    if isinstance(errors, list):
        items = []
        for error in errors:
            if isinstance(error, dict):
                location = str(error.get("location") or "document")
                items.append(f"{location}: {error.get('message')}")
        return tuple(items)
    reason = details.get("reason")
    if isinstance(reason, str):
        return tuple(line.strip() for line in reason.splitlines() if line.strip())
    other = {key: value for key, value in details.items() if key not in {"errors", "reason"}}
    return tuple(f"{key.replace('_', ' ')}: {_pairs(value)}" for key, value in other.items())


def _transport(error: ApiClientError, url: str | None, timeout: float | None) -> Problem:
    message = str(error)
    where = f" at {url}" if url else ""
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        limit = f"the {timeout:g} s timeout" if timeout else "its timeout"
        return Problem(
            "Backend did not respond",
            f"The request{where} exceeded {limit}.",
            "Check that the backend is not overloaded, or raise the timeout in the connection bar.",
        )
    if "refused" in lowered or "10061" in lowered:
        return Problem(
            "Backend unreachable",
            f"Nothing is listening{where} (connection refused).",
            "Start the backend on the Linux host (polmon-backend --host … --port …) and check "
            "the URL.",
        )
    if "name or service not known" in lowered or "getaddrinfo" in lowered or "11001" in lowered:
        return Problem(
            "Unknown host",
            f"The backend host name{where} could not be resolved.",
            "Check the spelling of the URL or use the server's IP address.",
        )
    if "reset" in lowered or "aborted" in lowered or "closed" in lowered:
        return Problem(
            "Connection dropped",
            f"The backend{where} closed the connection mid-request.",
            "The backend may have stopped or restarted; reconnect and retry.",
        )
    return Problem(
        "Backend unreachable",
        message.removeprefix("unable to reach backend: ").capitalize() + ".",
        "Check the URL, the network path and that the backend is running.",
    )


def describe(
    error: BaseException, *, url: str | None = None, timeout: float | None = None
) -> Problem:
    """Map ``error`` to a :class:`Problem`; unknown errors keep only their type and message."""
    if isinstance(error, ApiClientError):
        status, code, details = error.status, error.code, error.details
        message = str(error)
        backend_message = re.sub(r"^server returned HTTP \d+(?: \S+)?: ", "", message)
        if code == "malformed_response":
            return Problem(
                "Unexpected response",
                message[:1].upper() + message[1:],
                "Check that the URL points at a polmon backend of a compatible version.",
                code=code,
            )
        if status is None:
            return _transport(error, url, timeout)
        common = {"status": status, "code": code}
        if status == 401:
            return Problem(
                "API token required",
                "The backend rejected the request: a valid API token is required.",
                "Enter the backend's token (POLMON_API_TOKEN or its token file) in the "
                "connection bar.",
                **common,
            )
        if status in {404, 405}:
            return Problem(
                "Not supported by this backend",
                f"The backend does not provide this operation (HTTP {status}).",
                "The backend is older than this client; upgrade it to the same polmon version.",
                **common,
            )
        if status == 413:
            return Problem(
                "Document too large",
                backend_message,
                "Topology and scenario documents are limited to 2 MB.",
                items=validation_items(details),
                **common,
            )
        if status == 429:
            return Problem(
                "Refused by admission control",
                backend_message,
                "Reduce the workload, destroy other deployments, or raise the backend's "
                "configured limits.",
                items=limit_items(details),
                **common,
            )
        if status == 409:
            return Problem(
                "Conflict",
                backend_message,
                "Destroy or reset the conflicting deployment, then retry.",
                items=validation_items(details),
                **common,
            )
        if status == 422:
            return Problem(
                "Rejected",
                backend_message,
                "Correct the listed fields and validate again.",
                items=validation_items(details),
                **common,
            )
        if status >= 500:
            return Problem(
                "Backend error",
                f"The backend failed with HTTP {status}.",
                "Check the backend log (journalctl --user -u polmon-backend) and retry.",
                **common,
            )
        return Problem(
            f"Request failed (HTTP {status})",
            backend_message,
            items=validation_items(details),
            **common,
        )
    if isinstance(error, ValueError):
        return Problem(
            "Invalid settings", str(error), "Use a URL such as http://192.168.1.10:8080."
        )
    if isinstance(error, UnicodeDecodeError):
        return Problem("Unreadable file", "The file is not valid UTF-8 text.")
    if isinstance(error, OSError):
        filename = getattr(error, "filename", None)
        return Problem(
            "File error", error.strerror or str(error), f"File: {filename}" if filename else None
        )
    return Problem("Unexpected client error", f"{type(error).__name__}: {error}")
