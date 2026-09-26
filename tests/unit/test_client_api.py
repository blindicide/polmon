import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from polmon.client.api import ApiClient


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"name": "polmon", "version": "test", "status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def test_standard_library_client_connects_with_explicit_timeout() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ApiClient(f"http://127.0.0.1:{server.server_port}", timeout=1)
        assert client.health()["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)



def test_client_errors_carry_the_backend_error_document(tmp_path) -> None:
    import socket

    import pytest
    import uvicorn

    from polmon.api.control import ControlPlane
    from polmon.backend import create_app
    from polmon.client.api import ApiClientError

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(ControlPlane(tmp_path)), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        client = ApiClient(f"http://127.0.0.1:{port}", timeout=2)
        for _ in range(100):
            try:
                client.health()
                break
            except ApiClientError:
                threading.Event().wait(0.05)
        with pytest.raises(ApiClientError) as invalid:
            client.validate_topology("nodes: nope")
        assert invalid.value.status == 422 and invalid.value.code == "configuration_error"
        assert str(invalid.value).startswith("server returned HTTP 422 configuration_error:")
        assert "{" not in str(invalid.value)  # no Python dict repr in user-facing text
        with pytest.raises(ApiClientError) as missing:
            client.report("never-ran")
        assert missing.value.status == 422
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_client_rejects_non_http_urls_and_reports_unreachable_servers() -> None:
    import socket

    import pytest

    from polmon.client.api import ApiClientError

    for url in ("ftp://example", "localhost:8080", "http://"):
        with pytest.raises(ValueError):
            ApiClient(url)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(ApiClientError, match="unable to reach backend") as caught:
        ApiClient(f"http://127.0.0.1:{port}", timeout=1).health()
    assert caught.value.status is None


def test_connection_resets_become_client_errors() -> None:
    import socket
    import struct
    import sys

    import pytest

    from polmon.client.api import ApiClientError

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def reset_once() -> None:
        connection, _ = listener.accept()
        connection.recv(1024)
        # SO_LINGER with zero timeout makes close() send RST instead of FIN.
        layout = "HH" if sys.platform == "win32" else "ii"  # struct linger differs on Windows
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack(layout, 1, 0))
        connection.close()

    thread = threading.Thread(target=reset_once, daemon=True)
    thread.start()
    try:
        client = ApiClient(f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=3)
        with pytest.raises(ApiClientError) as caught:
            client.health()
        assert caught.value.status is None
        assert "backend" in str(caught.value)
    finally:
        thread.join(timeout=3)
        listener.close()
