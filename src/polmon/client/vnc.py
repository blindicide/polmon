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
        self._rfb_buffer = bytearray()
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

    def _read_ws_frame(self) -> bytes:
        assert self.sock is not None
        header = self._recv(2)
        length = header[1] & 127
        if length == 126:
            length = struct.unpack(">H", self._recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv(8))[0]
        return self._recv(length)

    def _read_frame(self, amount: int) -> bytes:
        while len(self._rfb_buffer) < amount:
            self._rfb_buffer.extend(self._read_ws_frame())
        result = bytes(self._rfb_buffer[:amount])
        del self._rfb_buffer[:amount]
        return result

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
        if self._read_frame(12) != b"RFB 003.008\n":
            raise RuntimeError("rfb_version_invalid")
        self._frame(b"RFB 003.008\n")
        security_count = self._read_frame(1)[0]
        security_types = self._read_frame(security_count)
        if security_count != 1 or 1 not in security_types:
            raise RuntimeError("rfb_security_refused")
        self._frame(b"\x01")
        if self._read_frame(4) != b"\x00\x00\x00\x00":
            raise RuntimeError("rfb_security_failed")
        self._frame(b"\x01")
        init = self._read_frame(24)
        self.width, self.height = struct.unpack(">HH", init[:4])
        name_length = struct.unpack(">I", init[20:24])[0]
        self._read_frame(name_length)
        self._frame(
            b"\x00\x00\x00\x00"
            + struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        )
        self._frame(b"\x02\x00\x00\x02" + struct.pack(">ii", 0, 5))
        self._frame(b"\x03\x00" + struct.pack(">HHHH", 0, 0, self.width, self.height))
        image = QImage(self.width, self.height, QImage.Format.Format_RGB32)
        while not self._stop.is_set():
            header = self._read_frame(4)
            if header[0] != 0:
                raise RuntimeError("rfb_message_unsupported")
            count = struct.unpack(">H", header[2:4])[0]
            for _ in range(count):
                x, y, width, height, encoding = struct.unpack(">HHHHI", self._read_frame(12))
                if encoding == 0:
                    self._read_raw(image, x, y, width, height)
                elif encoding == 5:
                    self._read_hextile(image, x, y, width, height)
                else:
                    raise RuntimeError("rfb_encoding_unsupported")
            self.frame_ready.emit(image.copy())

    def _read_pixel(self) -> int:
        blue, green, red, _ = self._read_frame(4)
        return (red << 16) | (green << 8) | blue

    def _fill(self, image: QImage, x: int, y: int, width: int, height: int, color: int) -> None:
        for row in range(y, y + height):
            for column in range(x, x + width):
                image.setPixel(column, row, color)

    def _read_raw(self, image: QImage, x: int, y: int, width: int, height: int) -> None:
        for row in range(y, y + height):
            for column in range(x, x + width):
                image.setPixel(column, row, self._read_pixel())

    def _read_hextile(self, image: QImage, x: int, y: int, width: int, height: int) -> None:
        background = 0
        foreground = 0
        for tile_y in range(0, height, 16):
            tile_height = min(16, height - tile_y)
            for tile_x in range(0, width, 16):
                tile_width = min(16, width - tile_x)
                subencoding = self._read_frame(1)[0]
                tile_origin_x, tile_origin_y = x + tile_x, y + tile_y
                if subencoding & 1:
                    self._read_raw(image, tile_origin_x, tile_origin_y, tile_width, tile_height)
                    continue
                if subencoding & 2:
                    background = self._read_pixel()
                self._fill(image, tile_origin_x, tile_origin_y, tile_width, tile_height, background)
                if subencoding & 4:
                    foreground = self._read_pixel()
                if not subencoding & 8:
                    continue
                subrectangles = self._read_frame(1)[0]
                colored = bool(subencoding & 16)
                for _ in range(subrectangles):
                    color = self._read_pixel() if colored else foreground
                    position = self._read_frame(1)[0]
                    size = self._read_frame(1)[0]
                    sub_x, sub_y = position >> 4, position & 0x0F
                    sub_width, sub_height = (size >> 4) + 1, (size & 0x0F) + 1
                    self._fill(
                        image,
                        tile_origin_x + sub_x,
                        tile_origin_y + sub_y,
                        sub_width,
                        sub_height,
                        color,
                    )

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
