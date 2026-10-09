"""Built-in ``static_http`` laboratory service: a fixed response and no filesystem access.

Standalone and standard-library only. The namespace backend runs this file by path with an
isolated interpreter (``python -I -S static_http.py --bind ADDR --port PORT``) inside the lab
namespace after dropping privileges, so it never sees the backend's working directory, environment,
or site-packages. Requests are read with hard size and time limits.
"""

from __future__ import annotations

import argparse
import socketserver
import threading

BODY = b"polmon static_http laboratory service\n"
HTTP_MODE_FLAG = "--polmon-run-namespace-http-service"
MAX_LINE_BYTES = 4_096
MAX_REQUEST_BYTES = 8_192
MAX_CONCURRENT = 32
READ_TIMEOUT_SECONDS = 5.0


def response(request_line: bytes, oversized: bool) -> bytes:
    parts = request_line.split()
    if oversized or len(parts) != 3 or not parts[2].startswith(b"HTTP/"):
        status, body = b"400 Bad Request", b"bad request\n"
    elif parts[0] in (b"GET", b"HEAD"):
        status, body = b"200 OK", BODY
    else:
        status, body = b"405 Method Not Allowed", b"method not allowed\n"
    head = (
        b"HTTP/1.0 "
        + status
        + b"\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
        + str(len(body)).encode("ascii")
        + b"\r\nConnection: close\r\n\r\n"
    )
    return head if parts[:1] == [b"HEAD"] else head + body


class Handler(socketserver.StreamRequestHandler):
    timeout = READ_TIMEOUT_SECONDS

    def handle(self) -> None:
        try:
            request_line = self.rfile.readline(MAX_LINE_BYTES)
            total = len(request_line)
            while total <= MAX_REQUEST_BYTES:
                line = self.rfile.readline(MAX_LINE_BYTES)
                total += len(line)
                if line in (b"\r\n", b"\n", b""):
                    break
            self.wfile.write(response(request_line, total > MAX_REQUEST_BYTES))
        except OSError:  # includes read timeouts and peers that disconnect early
            return


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = MAX_CONCURRENT

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, Handler)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    def process_request(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)  # over the concurrency bound: drop, never queue
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:  # type: ignore[no-untyped-def]
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="polmon static_http laboratory service")
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    with Server((args.bind, args.port)) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
