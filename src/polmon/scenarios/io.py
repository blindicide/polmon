"""Scenario YAML loading with stable validation errors."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from polmon.core.errors import ConfigurationError
from polmon.scenarios.models import Scenario
from polmon.topology.io import UniqueKeyLoader


def parse_scenario(text: str) -> Scenario:
    try:
        raw = yaml.load(text, Loader=UniqueKeyLoader)
        if not isinstance(raw, dict):
            raise ConfigurationError("scenario document must be a YAML mapping")
        return Scenario.model_validate(raw)
    except ConfigurationError:
        raise
    except yaml.YAMLError as error:
        raise ConfigurationError("invalid scenario YAML", details={"reason": str(error)}) from error
    except ValidationError as error:
        errors = [
            {"location": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]
        raise ConfigurationError(
            "scenario validation failed", details={"errors": errors}
        ) from error


def load_scenario(path: str | Path) -> Scenario:
    try:
        return parse_scenario(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(
            "unable to read scenario", details={"reason": str(error)}
        ) from error
