"""Single-frame AF_PACKET writer, entered only by the namespace backend.

The process must already be inside a managed network namespace. It accepts one bounded
hexadecimal frame on stdin and never chooses a namespace, route, or host interface.
"""

from __future__ import annotations

import os
import re
import socket
import sys

PACKET_MODE_FLAG = "--polmon-run-namespace-packet-writer"
_MANAGED_NAMESPACE = re.compile(r"polmon[0-9a-f]{8}n\Z")


def _inside_managed_namespace(namespace: str) -> bool:
    """Refuse a direct helper invocation from the host namespace."""
    if _MANAGED_NAMESPACE.fullmatch(namespace) is None:
        return False
    try:
        current = os.stat("/proc/self/ns/net").st_ino
        managed = os.stat(f"/run/netns/{namespace}").st_ino
        host = os.stat("/proc/1/ns/net").st_ino
    except OSError:
        return False
    return current == managed and current != host and {
        name for _, name in socket.if_nameindex()
    } == {"lo", "eth0"}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[1] != "eth0" or not _inside_managed_namespace(args[0]):
        return 2
    encoded = sys.stdin.read(3029)
    if len(encoded) < 28 or len(encoded) > 3028:
        return 2
    try:
        frame = bytes.fromhex(encoded)
    except ValueError:
        return 2
    if not 14 <= len(frame) <= 1514:
        return 2
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as writer:
        writer.bind((args[1], 0))
        written = writer.send(frame)
    if written != len(frame):
        return 3
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
