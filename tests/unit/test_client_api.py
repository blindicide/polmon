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

