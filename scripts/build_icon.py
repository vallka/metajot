"""Renders src/metajot/data/icon.svg into icon.ico (all standard Windows icon
sizes, each rendered from the SVG rather than downscaled from one bitmap, so
small sizes stay crisp). Run after editing the SVG:

    uv run python scripts/build_icon.py
"""

import os
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "metajot" / "data"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def render(renderer: QSvgRenderer, size: int) -> Image.Image:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> None:
    app = QGuiApplication([])  # noqa: F841 - needed for QPainter
    renderer = QSvgRenderer(str(DATA_DIR / "icon.svg"))
    if not renderer.isValid():
        raise SystemExit("icon.svg could not be parsed")

    images = [render(renderer, size) for size in SIZES]
    largest = images[-1]
    largest.save(
        DATA_DIR / "icon.ico",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    print(f"Wrote {DATA_DIR / 'icon.ico'} ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
