"""Stable application error types shared by API and execution layers."""

from __future__ import annotations


class PolmonError(Exception):
    """Base error with a public code and safe user-facing message."""

    code = "polmon_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(PolmonError):
    """Raised when supplied configuration is invalid."""

    code = "configuration_error"
    status_code = 422

