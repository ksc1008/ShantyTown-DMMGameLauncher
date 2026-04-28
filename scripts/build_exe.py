"""Build a single-file Windows executable for distribution.

Run from the project root:

    uv run python scripts/build_exe.py

Outputs ``dist/shantytown.exe``. Hand that one file to the user — no
Python install, no extra files, double-click to run. PyInstaller's
bootloader extracts bundled resources to ``%LOCALAPPDATA%\\Temp\\_MEI*``
on launch and cleans up on exit, transparent to our code.

Two phases:

1. Render ``app_icon.svg`` into a multi-resolution ``.ico`` (PyInstaller
   wants ``.ico`` for the Windows exe icon — 16/24/32/48/64/128/256 so
   the OS picks the right size for taskbar / alt-tab / file explorer).
2. Invoke ``pyinstaller`` with ``--onefile --windowed``, the new icon,
   and the bundled resource directory.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "src" / "shantytown" / "resources" / "icons" / "app_icon.svg"
ICO = ROOT / "build" / "app_icon.ico"
ENTRY = ROOT / "src" / "shantytown" / "__main__.py"
DIST = ROOT / "dist"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def build_ico() -> None:
    """Render the SVG once per ICO entry size and assemble a multi-image ICO.

    ICO entries store independent images so Windows can pick the
    sharpest option for each context. Rendering each size from the
    SVG is much sharper than downsampling a single 256-px raster.
    """
    # Defer Qt imports so a misconfigured environment surfaces only on
    # the build step, not on import of this module.
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    if QGuiApplication.instance() is None:
        QGuiApplication(sys.argv)

    if not SVG.is_file():
        raise FileNotFoundError(f"Source icon missing: {SVG}")

    renderer = QSvgRenderer(str(SVG))
    png_blobs: list[bytes] = []
    for s in ICO_SIZES:
        img = QImage(s, s, QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()

        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        png_blobs.append(bytes(ba))

    # ICO file format:
    #   ICONDIR (6 bytes): reserved=0, type=1, count=N
    #   ICONDIRENTRY (16 bytes) × N: width, height, color count, reserved,
    #       planes, bit count, bytes_in_res, image_offset
    #   image data × N: each PNG blob
    out = BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(ICO_SIZES)))

    header_size = 6 + 16 * len(ICO_SIZES)
    cumulative = header_size
    offsets: list[int] = []
    for blob in png_blobs:
        offsets.append(cumulative)
        cumulative += len(blob)

    for s, blob, offset in zip(ICO_SIZES, png_blobs, offsets, strict=True):
        # Width/height of 0 in ICO entry header means "256 or larger".
        w = 0 if s >= 256 else s
        h = 0 if s >= 256 else s
        out.write(
            struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        )

    for blob in png_blobs:
        out.write(blob)

    ICO.parent.mkdir(parents=True, exist_ok=True)
    ICO.write_bytes(out.getvalue())
    print(f"[build_ico] {ICO}  ({len(png_blobs)} sizes)")


def build_exe() -> None:
    """Drive PyInstaller. ``--onefile`` for single-file output,
    ``--windowed`` so no console window flashes on launch."""
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "shantytown",
        "--icon",
        str(ICO),
        # Bundle the resources tree under the package's expected path so
        # ``Path(__file__).resolve().parents[1] / "resources"`` keeps
        # working at runtime (PyInstaller extracts to a temp dir whose
        # layout mirrors the source tree).
        "--add-data",
        f"src/shantytown/resources{sep}shantytown/resources",
        # Help the analyser find the package without an editable install.
        "--paths",
        "src",
        str(ENTRY),
    ]
    print(f"[build_exe] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)
    out = DIST / ("shantytown.exe" if sys.platform == "win32" else "shantytown")
    print(f"[build_exe] {out}")


def main() -> None:
    print("=== Building shantytown ===")
    build_ico()
    build_exe()
    print()
    print(f"Done. Distribute {DIST / 'shantytown.exe'}")


if __name__ == "__main__":
    main()
