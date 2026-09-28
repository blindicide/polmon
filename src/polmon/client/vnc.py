"""Small authenticated WebSocket/RFB client for the namespace VNC relay."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlparse

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import QWidget


class VncViewer(QWidget):
    frame_ready = Signal(QImage)
    failed = Signal(str)

    def __init__(
        self, relay_url: str, token: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self._image = QImage()
        self._socket: RelaySocket | None = None
        self.frame_ready.connect(self._set_image)
        self._socket = RelaySocket(relay_url, token, self.frame_ready, self.failed)
        self._socket.start()

    def _set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), "#101419")
        if not self._image.isNull():
            painter.drawImage(self.rect(), self._image)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._socket is not None:
            self._socket.pointer(event.position().x(), event.position().y(), 1)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._socket is not None:
            self._socket.pointer(event.position().x(), event.position().y(), 0)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._socket is not None:
            self._socket.key(event.text(), True)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._socket is not None:
            self._socket.key(event.text(), False)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._socket is not None:
            self._socket.close()
        super().closeEvent(event)


class RelaySocket(threading.Thread):
    def __init__(self, url: str, token: str | None, frame_ready: Signal, failed: Signal) -> None:
        super().__init__(daemon=True, name="polmon-vnc")
        self.url, self.token = url, token
        self.frame_ready, self.failed = frame_ready, failed
        self.sock: socket.socket | None = None
        self.width = self.height = 0
        self._stop = threading.Event()

    def run(self) -> None:
        try:
            self.sock = self._connect()
            self._rfb()
        except Exception as error:
            self.failed.emit(f"console.vnc_relay_failed:{type(error).__name__}")  # i18n: allow
        finally:
            if self.sock is not None:
                self.sock.close()

    def _connect(self) -> socket.socket:
        parsed = urlparse(self.url)
        sock = socket.create_connection((parsed.hostname, parsed.port or 80), 10)
        if parsed.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        headers = (  # i18n: allow
            f"GET {path} HTTP/1.1\r\nHost: {parsed.hostname}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
        )  # i18n: allow
        if self.token:
            headers += f"Authorization: Bearer {self.token}\r\n"
        sock.sendall((headers + "\r\n").encode())
        response = self._read_until(sock, b"\r\n\r\n")
        if not response.startswith(b"HTTP/1.1 101"):
            raise RuntimeError("websocket_upgrade_refused")
        magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # i18n: allow
        expected = base64.b64encode(hashlib.sha1((key + magic).encode()).digest()).decode()
        if expected.encode() not in response:
            raise RuntimeError("websocket_accept_invalid")
        return sock

    @staticmethod
    def _read_until(sock: socket.socket, marker: bytes) -> bytes:
        data = b""
        while marker not in data and len(data) < 65536:
            data += sock.recv(4096)
        return data

    def _frame(self, payload: bytes) -> None:
        assert self.sock is not None
        mask = os.urandom(4)
        encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        length = len(encoded)
        header = (
            bytes([0x82, 0x80 | length])
            if length < 126
            else bytes([0x82, 0x80 | 126]) + struct.pack(">H", length)
        )
        self.sock.sendall(header + mask + encoded)

    def _read_frame(self) -> bytes:
        assert self.sock is not None
        header = self._recv(2)
        length = header[1] & 127
        if length == 126:
            length = struct.unpack(">H", self._recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv(8))[0]
        return self._recv(length)

    def _recv(self, amount: int) -> bytes:
        assert self.sock is not None
        data = b""
        while len(data) < amount:
            part = self.sock.recv(amount - len(data))
            if not part:
                raise ConnectionError("relay_closed")
            data += part
        return data

    def _rfb(self) -> None:
        assert self.sock is not None
        if self._read_frame() != b"RFB 003.008\n":
            raise RuntimeError("rfb_version_invalid")
        self._frame(b"RFB 003.008\n")
        security = self._read_frame()
        if security[0] != 1 or security[1:5] != b"\x00\x00\x00\x00":
            raise RuntimeError("rfb_security_refused")
        self._frame(b"\x01")
        init = self._read_frame()
        self.width, self.height = struct.unpack(">HH", init[:4])
        self._frame(b"\x00")
        self._frame(b"\x02\x00\x00\x00\x01\x00\x00\x00\x01")
        self._frame(b"\x03\x00\x00\x00\x00\x00\x00\x00\x00")
        image = QImage(self.width, self.height, QImage.Format.Format_RGB32)
        while not self._stop.is_set():
            payload = self._read_frame()
            if payload and payload[0] == 0:
                count = struct.unpack(">H", payload[1:3])[0]
                offset = 3
                for _ in range(count):
                    x, y, width, height, encoding = struct.unpack(
                        ">HHHHI", payload[offset : offset + 12]
                    )
                    offset += 12
                    if encoding != 0:
                        raise RuntimeError("rfb_encoding_unsupported")
                    for row in range(height):
                        for column in range(width):
                            blue, green, red, _ = payload[offset:offset + 4]
                            offset += 4
                            image.setPixel(x + column, y + row, (red << 16) | (green << 8) | blue)
                self.frame_ready.emit(image.copy())

    def pointer(self, x: float, y: float, buttons: int) -> None:
        if self.sock is not None and self.width and self.height:
            self._frame(b"\x05" + bytes([buttons]) + struct.pack(">HH", int(x), int(y)))

    def key(self, text: str, down: bool) -> None:
        if self.sock is not None and text:
            self._frame(
                b"\x04"
                + bytes([1 if down else 0])
                + b"\x00\x00"
                + struct.pack(">I", ord(text[0]))
            )

    def close(self) -> None:
        self._stop.set()
        if self.sock is not None:
            self.sock.close()
