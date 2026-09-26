"""The polmon application icon, drawn with QPainter (no image files to package).

``python -m polmon.client.icon OUTPUT.ico|.png`` writes it to a file; the Windows spec uses this
to embed the same icon in the executable.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap

SIZES = (16, 24, 32, 48, 64, 128, 256)
BACKGROUND = "#1f6feb"
FOREGROUND = "#ffffff"
# A small isolated network: a hub linked to three endpoints, two of them peered (unit coords).
NODES = ((0.50, 0.53), (0.24, 0.27), (0.77, 0.30), (0.50, 0.84))
LINKS = ((0, 1), (0, 2), (0, 3), (1, 2))


def draw_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BACKGROUND))
    painter.drawRoundedRect(rect, size * 0.22, size * 0.22)

    def point(index: int) -> QPointF:
        x, y = NODES[index]
        return QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height())

    painter.setPen(
        QPen(
            QColor(FOREGROUND),
            max(1.0, size * 0.055),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    for start, end in LINKS:
        painter.drawLine(point(start), point(end))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(FOREGROUND))
    for index in range(len(NODES)):
        radius = size * (0.105 if index == 0 else 0.08)
        painter.drawEllipse(point(index), radius, radius)
    painter.end()
    return image


def app_icon() -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(QPixmap.fromImage(draw_icon(size)))
    return icon


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m polmon.client.icon OUTPUT.ico|OUTPUT.png", file=sys.stderr)
        return 2
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - needed for painting
    target = args[0]
    size = 256
    if not draw_icon(size).save(target):
        print(f"could not write {target}", file=sys.stderr)
        return 1
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
