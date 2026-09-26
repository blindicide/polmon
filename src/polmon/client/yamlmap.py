"""Map validation error locations (``nodes.1.interfaces.0.ipv4``) to YAML line numbers."""

from __future__ import annotations

import re

import yaml

MARK = re.compile(r"line (\d+), column (\d+)")


def locate(source: str, location: str) -> int | None:
    """One-based line of the node at a dotted ``location``, or of its closest ancestor."""
    try:
        node = yaml.compose(source, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return reason_line(location)
    if node is None:
        return None
    line = node.start_mark.line + 1
    for part in location.split("."):
        if isinstance(node, yaml.MappingNode):
            match = next((value for key, value in node.value if key.value == part), None)
            if match is None:
                break
            key_node = next(key for key, value in node.value if value is match)
            line = key_node.start_mark.line + 1
            node = match
        elif isinstance(node, yaml.SequenceNode) and part.isdigit():
            index = int(part)
            if index >= len(node.value):
                break
            node = node.value[index]
            line = node.start_mark.line + 1
        else:
            break
    return line


def reason_line(reason: str) -> int | None:
    """First ``line N`` mark in a YAML parser message (PyYAML marks are one-based)."""
    match = MARK.search(reason)
    return int(match.group(1)) if match else None


def document_id(source: str) -> str | None:
    """The top-level ``id`` of a YAML document, without validating anything else."""
    try:
        document = yaml.safe_load(source)
    except yaml.YAMLError:
        return None
    value = document.get("id") if isinstance(document, dict) else None
    return value if isinstance(value, str) else None
