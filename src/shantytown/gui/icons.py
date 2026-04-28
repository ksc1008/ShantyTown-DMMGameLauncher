"""Bundled Fluent UI System Icons + recoloring helper.

We ship a small set of MIT-licensed SVGs from
`microsoft/fluentui-system-icons <https://github.com/microsoft/fluentui-system-icons>`_
in ``resources/icons/``. They're black-on-transparent by default;
``render_icon`` renders them at the requested size and recolors the
opaque pixels using ``CompositionMode_SourceIn`` so the same asset can
serve both light and dark themes (just pass a different color).

Caching: the function caches by ``(name, size, color)`` because cards
may render the same icon many times during a session and SVG parsing
is not free.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

ICONS_DIR = Path(__file__).resolve().parents[1] / "resources" / "icons"


@lru_cache(maxsize=64)
def render_icon(name: str, size: int, color: str) -> QPixmap:
    """Render ``<name>.svg`` at ``size`` x ``size`` filled with ``color``.

    Args:
        name: File basename without extension (e.g. ``"settings"``).
        size: Square dimension in pixels.
        color: Any Qt-parsable color (``"#0067c0"``, ``"black"``).

    Returns:
        A ``QPixmap`` with transparent background and the icon shape
        filled with ``color``. Returns an empty pixmap if the SVG file
        is missing.
    """
    svg_path = ICONS_DIR / f"{name}.svg"
    if not svg_path.is_file():
        empty = QPixmap(size, size)
        empty.fill(Qt.GlobalColor.transparent)
        return empty

    renderer = QSvgRenderer(str(svg_path))
    base = QPixmap(QSize(size, size))
    base.fill(Qt.GlobalColor.transparent)
    p = QPainter(base)
    renderer.render(p)
    p.end()

    out = QPixmap(QSize(size, size))
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.drawPixmap(0, 0, base)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


def make_icon(name: str, size: int, color: str) -> QIcon:
    """Convenience for QPushButton.setIcon(...)."""
    return QIcon(render_icon(name, size, color))


def app_icon() -> QIcon:
    """The full-color app icon (used by the taskbar and window title).

    Returns a multi-resolution QIcon backed by the bundled SVG so Qt
    rasterises at whatever size the host platform asks for (16 in the
    title bar, 32-256 in the taskbar / alt-tab).
    """
    svg = ICONS_DIR / "app_icon.svg"
    return QIcon(str(svg))
