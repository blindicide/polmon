"""Safe YAML loading with duplicate-key detection and stable error conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from polmon.core.errors import CodedValueError, ConfigurationError
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


# PyYAML problem phrases (the parser's English) mapped to stable codes a client can localize.
YAML_PROBLEMS = (
    ("duplicate YAML key", "duplicate_key"),
    ("mapping values are not allowed", "mapping_values_not_allowed"),
    ("could not find expected ':'", "expected_colon"),
    ("cannot start any token", "invalid_character"),
    ("expected <block end>", "bad_indentation"),
    ("did not find expected key", "bad_indentation"),
    ("did not find expected '-' indicator", "bad_indentation"),
    ("found unexpected end of stream", "unexpected_end"),
    ("found undefined alias", "undefined_alias"),
    ("did not find expected node content", "missing_value"),
    ("found unknown escape character", "invalid_escape"),
    ("found unexpected ':'", "unexpected_colon"),
)
# Pydantic error context values that are useful, JSON-safe parameters for a message.
CONTEXT_PARAMETERS = ("expected", "ge", "gt", "le", "lt", "min_length", "max_length", "pattern")


def yaml_error(document: str, error: yaml.YAMLError) -> ConfigurationError:
    """A coded refusal for invalid YAML with the line/column and a stable problem code."""
    problem = str(getattr(error, "problem", "") or error)
    mark = getattr(error, "problem_mark", None)
    line = mark.line + 1 if mark is not None else None
    column = mark.column + 1 if mark is not None else None
    problem_code = next((code for phrase, code in YAML_PROBLEMS if phrase in problem), "syntax")
    key = problem.split(":", 1)[1].strip().strip("'\"") if problem_code == "duplicate_key" else ""
    return ConfigurationError(
        f"invalid {document} YAML",
        details={
            "reason": str(error),
            "line": line,
            "column": column,
            "problem": problem,
            "problem_code": problem_code,
            "key": key,
        },
        message_code=f"{document}.yaml_invalid",
        params={"line": line if line is not None else "?", "column": column or "?"},
    )


def validation_errors(error: ValidationError) -> list[dict[str, object]]:
    """Pydantic errors as ``location``/``message`` plus ``message_code``/``params`` items."""
    items: list[dict[str, object]] = []
    for item in error.errors(include_url=False, include_input=False):
        context = item.get("ctx") or {}
        cause = context.get("error")
        if isinstance(cause, CodedValueError):
            code, params = cause.message_code, dict(cause.params)
        else:
            code = f"pydantic.{item['type']}"
            params = {
                name: str(context[name]) for name in CONTEXT_PARAMETERS if name in context
            }
        location = ".".join(str(part) for part in item["loc"])
        if code in {"topology.address_outside_profile", "topology.address_outside_lab"}:
            location = f"networks.{params.get('network_index', 0)}.ipv4_subnet"
        items.append(
            {
                "location": location,
                "message": item["msg"],
                "message_code": code,
                "params": params,
            }
        )
    return items


def parse_topology(text: str, *, migration: bool = False) -> Topology:
    try:
        raw = yaml.load(text, Loader=UniqueKeyLoader)
        if not isinstance(raw, dict):
            raise ConfigurationError(
                "topology document must be a YAML mapping",
                message_code="topology.not_mapping",
            )
        if migration:
            # v0.4 documents had no discriminator and accepted the broader ranges.
            # The migration path opts into that legacy parser context only long enough
            # to produce a default-profile document.
            raw.setdefault("address_space", "rfc1918")
        return Topology.model_validate(raw)
    except ConfigurationError:
        raise
    except yaml.YAMLError as error:
        raise yaml_error("topology", error) from error
    except ValidationError as error:
        raise ConfigurationError(
            "topology validation failed",
            details={"errors": validation_errors(error)},
            message_code="topology.validation_failed",
        ) from error


def load_topology(path: str | Path) -> Topology:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(
            "unable to read topology", details={"reason": str(error)},
            message_code="topology.unreadable",
        ) from error
    return parse_topology(text)


def dump_topology(topology: Topology) -> str:
    payload = topology.model_dump(mode="json", by_alias=True, exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
