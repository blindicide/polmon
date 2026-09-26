"""Safe YAML loading with duplicate-key detection and stable error conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from polmon.core.errors import ConfigurationError
from polmon.topology.models import Topology


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader variant that refuses ambiguous duplicate mapping keys."""


def _construct_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.MarkedYAMLError(
                problem=f"duplicate YAML key: {key!r}", problem_mark=key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def parse_topology(text: str) -> Topology:
    try:
        raw = yaml.load(text, Loader=UniqueKeyLoader)
        if not isinstance(raw, dict):
            raise ConfigurationError("topology document must be a YAML mapping")
        return Topology.model_validate(raw)
    except ConfigurationError:
        raise
    except yaml.YAMLError as error:
        raise ConfigurationError("invalid topology YAML", details={"reason": str(error)}) from error
    except ValidationError as error:
        errors = [
            {"location": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        ]
        raise ConfigurationError(
            "topology validation failed", details={"errors": errors}
        ) from error


def load_topology(path: str | Path) -> Topology:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(
            "unable to read topology", details={"reason": str(error)}
        ) from error
    return parse_topology(text)


def dump_topology(topology: Topology) -> str:
    payload = topology.model_dump(mode="json", by_alias=True, exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
