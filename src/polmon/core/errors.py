"""Stable application error types shared by API and execution layers.

Every error carries a machine ``message_code`` and ``params`` next to its English ``message``.
The HTTP API returns all three; clients render ``message_code`` in their own language (the
desktop client's catalogs hold ``backend.<message_code>``) and keep ``message`` for logs and
API consumers. Codes are stable identifiers: rename one only together with the client catalogs.
"""

from __future__ import annotations

from collections.abc import Mapping

JsonScalar = str | int | float | bool | None


def _params(values: Mapping[str, object] | None) -> dict[str, JsonScalar]:
    """Keep parameters JSON-safe: scalars as they are, anything else as text."""
    safe: dict[str, JsonScalar] = {}
    for key, value in (values or {}).items():
        if isinstance(value, str | int | float | bool) or value is None:
            safe[key] = value
        elif isinstance(value, list | tuple | set | frozenset):
            safe[key] = ", ".join(str(item) for item in value)
        else:
            safe[key] = str(value)
    return safe


class PolmonError(Exception):
    """Base error with a public code, a safe English message and a localizable message code."""

    code = "polmon_error"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
        message_code: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.message_code = message_code or f"generic.{self.code}"
        self.params = _params(params)

    def document(self) -> dict[str, object]:
        """The ``error`` object of an API error response."""
        return {
            "code": self.code,
            "message": self.message,
            "message_code": self.message_code,
            "params": self.params,
            "details": self.details,
        }


class ConfigurationError(PolmonError):
    """Raised when supplied configuration is invalid."""

    code = "configuration_error"
    status_code = 422


class CodedValueError(ValueError):
    """A validator failure (inside Pydantic models) that keeps its message code and params.

    Pydantic wraps it into a ``value_error`` whose context still holds this exception, so the
    YAML loaders can report ``message_code``/``params`` for each validation error item.
    """

    def __init__(self, message: str, message_code: str, **params: object) -> None:
        super().__init__(message)
        self.message_code = message_code
        self.params = _params(params)
