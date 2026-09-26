import socket
import threading

import pytest

from polmon.backends.namespace import static_http


@pytest.fixture
def server():
    instance = static_http.Server(("127.0.0.1", 0))
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance.server_address[1]
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def exchange(port: int, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        connection.sendall(payload)
        chunks = []
        while chunk := connection.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks)


def test_get_returns_the_fixed_body_and_never_lists_files(server) -> None:
    reply = exchange(server, b"GET / HTTP/1.0\r\nHost: lab\r\n\r\n")
    assert reply.startswith(b"HTTP/1.0 200 OK\r\n")
    assert reply.endswith(static_http.BODY)
    for path in (b"/", b"/etc/passwd", b"/../../", b"/.git/config"):
        body = exchange(server, b"GET " + path + b" HTTP/1.0\r\n\r\n").split(b"\r\n\r\n", 1)[1]
        assert body == static_http.BODY  # the path is never used


def test_head_other_methods_and_malformed_or_oversized_requests(server) -> None:
    head = exchange(server, b"HEAD / HTTP/1.0\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 200 OK") and head.endswith(b"\r\n\r\n")
    assert exchange(server, b"POST / HTTP/1.0\r\n\r\n").startswith(b"HTTP/1.0 405")
    assert exchange(server, b"nonsense\r\n\r\n").startswith(b"HTTP/1.0 400")
    flood = b"GET / HTTP/1.0\r\n" + b"X-Pad: " + b"a" * 1000 + b"\r\n"
    assert exchange(server, flood * 20 + b"\r\n").startswith(b"HTTP/1.0 400")
