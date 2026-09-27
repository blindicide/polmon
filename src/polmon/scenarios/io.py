"""Scenario YAML loading with stable validation errors."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from polmon.core.errors import ConfigurationError
from polmon.scenarios.models import Scenario
from polmon.topology.io import UniqueKeyLoader, validation_errors, yaml_error


def parse_scenario(text: str) -> Scenario:
    try:
        raw = yaml.load(text, Loader=UniqueKeyLoader)
        if not isinstance(raw, dict):
            raise ConfigurationError(
                "scenario document must be a YAML mapping",
                message_code="scenario.not_mapping",
            )
        return Scenario.model_validate(raw)
    except ConfigurationError:
        raise
    except yaml.YAMLError as error:
        raise yaml_error("scenario", error) from error
    except ValidationError as error:
        raise ConfigurationError(
            "scenario validation failed",
            details={"errors": validation_errors(error)},
            message_code="scenario.validation_failed",
        ) from error


def load_scenario(path: str | Path) -> Scenario:
    try:
        return parse_scenario(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(
            "unable to read scenario", details={"reason": str(error)},
            message_code="scenario.unreadable",
        ) from error
