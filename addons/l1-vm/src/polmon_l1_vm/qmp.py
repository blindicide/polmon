"""Минимальный клиент QMP: одна команда на соединение, с ограничениями по времени и объёму."""

from __future__ import annotations

import json
import socket
import time

from polmon_l1_vm.images import VMError

MAX_BYTES = 65_536


def _connect(path: str, timeout: float) -> socket.socket:
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise OSError("Unix sockets are unavailable")
    stream = socket.socket(family, socket.SOCK_STREAM)
    try:
        stream.settimeout(timeout)
        stream.connect(path)
    except OSError:
        stream.close()
        raise
    return stream


def command(path: str, name: str, *, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    received = 0
    try:
        with _connect(path, timeout) as stream:
            reader = stream.makefile("rb")

            def message() -> dict:
                nonlocal received
                while time.monotonic() < deadline:
                    line = reader.readline(MAX_BYTES + 1)
                    received += len(line)
                    if not line or received > MAX_BYTES:
                        raise VMError("vm.qmp_failed")
                    return json.loads(line)
                raise VMError("vm.qmp_timeout")

            message()  # приветствие сервера
            stream.sendall(b'{"execute":"qmp_capabilities"}\n')
            while "return" not in (reply := message()):
                if "error" in reply:
                    raise VMError("vm.qmp_failed")
            stream.sendall(json.dumps({"execute": name}).encode() + b"\n")
            while True:
                reply = message()
                if "return" in reply:
                    return reply["return"]
                if "error" in reply:
                    raise VMError("vm.qmp_failed")
    except (OSError, ValueError) as error:
        raise VMError("vm.qmp_failed") from error
