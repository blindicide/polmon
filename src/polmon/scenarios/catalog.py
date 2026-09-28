"""Closed command catalogue for automated SSH scenario actions."""

from __future__ import annotations

import re
from collections.abc import Mapping

from polmon.core.errors import CodedValueError

COMMANDS = frozenset(
    {
        "hostname",
        "cat_hostname",
        "ip_addr",
        "ip_route",
        "ip_neigh",
        "ps",
        "uptime",
        "false",
        "sleep",
        "ping",
        "nc",
    }
)
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_PARAMETERS: dict[str, frozenset[str]] = {
    "hostname": frozenset(),
    "cat_hostname": frozenset(),
    "ip_addr": frozenset(),
    "ip_route": frozenset(),
    "ip_neigh": frozenset(),
    "ps": frozenset(),
    "uptime": frozenset(),
    "false": frozenset(),
    "sleep": frozenset({"seconds"}),
    "ping": frozenset({"host", "count"}),
    "nc": frozenset({"host", "port", "listen"}),
}


def _integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CodedValueError(
            f"{name} must be an integer from {minimum} to {maximum}",
            "scenario.command_parameter_invalid",
            parameter=name,
        )
    return value


def validate_command(command: str | None, parameters: Mapping[str, object]) -> None:
    if command not in COMMANDS:
        raise CodedValueError(
            f"unknown automated command '{command}'",
            "scenario.command_unknown",
            command=command or "",
        )
    unknown = sorted(set(parameters) - _PARAMETERS[command])
    if unknown:
        raise CodedValueError(
            f"command '{command}' has unsupported parameters: {', '.join(unknown)}",
            "scenario.command_parameter_unknown",
            command=command,
            parameters=unknown,
        )
    if command == "sleep":
        _integer(parameters.get("seconds"), name="seconds", minimum=1, maximum=30)
    if command == "ping":
        host = parameters.get("host")
        if not isinstance(host, str) or not _IDENTIFIER.fullmatch(host):
            raise CodedValueError(
                "ping host must be a topology node identifier",
                "scenario.command_parameter_invalid",
                parameter="host",
            )
        _integer(parameters.get("count"), name="count", minimum=1, maximum=4)
    if command == "nc":
        host = parameters.get("host")
        if not isinstance(host, str) or not _IDENTIFIER.fullmatch(host):
            raise CodedValueError(
                "nc host must be a topology node identifier",
                "scenario.command_parameter_invalid",
                parameter="host",
            )
        _integer(parameters.get("port"), name="port", minimum=1, maximum=65535)
        if not isinstance(parameters.get("listen"), bool):
            raise CodedValueError(
                "nc listen must be boolean",
                "scenario.command_parameter_invalid",
                parameter="listen",
            )


def command_argv(
    command: str, parameters: Mapping[str, object], host_addresses: Mapping[str, str]
) -> list[str]:
    validate_command(command, parameters)
    if command == "hostname":
        return ["hostname"]
    if command == "cat_hostname":
        return ["cat", "/etc/hostname"]
    if command == "ip_addr":
        return ["ip", "-o", "-4", "addr"]
    if command == "ip_route":
        return ["ip", "route"]
    if command == "ip_neigh":
        return ["ip", "neigh"]
    if command == "ps":
        return ["ps"]
    if command == "uptime":
        return ["uptime"]
    if command == "false":
        return ["false"]
    if command == "sleep":
        return ["sleep", str(parameters["seconds"])]
    host = str(parameters["host"])
    if host not in host_addresses:
        raise CodedValueError(
            f"command target '{host}' is not in the required topology",
            "scenario.command_target_unknown",
            target=host,
        )
    if command == "ping":
        return ["ping", "-c", str(parameters["count"]), host_addresses[host]]
    if command == "nc":
        prefix = ["nc", "-z", "-w", "2"]
        if parameters["listen"]:
            return ["nc", "-l", "-w", "2", str(parameters["port"])]
        return [*prefix, host_addresses[host], str(parameters["port"])]
    raise AssertionError(f"unhandled catalogue command {command}")
