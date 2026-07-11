"""Build the Windows distribution for shantytown.

Run from the project root:

    uv run python scripts/build_exe.py               # both (main + helper)
    uv run python scripts/build_exe.py --target main
    uv run python scripts/build_exe.py --target helper

Produces TWO single-file exes in ``dist/``:

- **main** (``shantytown.exe``) — the app. Built ``--onefile --windowed``
  with QtWebEngine EXCLUDED, so its startup unpack is much smaller/faster.
  It does everything except in-process webview login.
- **helper** (``__loginhelper.exe``) — the webview login engine. Built
  ``--onefile`` (console, no window) WITH QtWebEngine. The main app spawns
  it only when a webview login is needed and talks over stdin/stdout
  (see ``gui.webview_login_client``). Keep it next to ``shantytown.exe``.

Shipping only ``shantytown.exe`` gives a browser-only install: webview
login is hidden and the browser flow is forced (the app detects the
missing helper via ``gui.webview_support``) — nothing crashes.

Phases:

1. Render ``app_icon.svg`` into a multi-resolution ``.ico`` (once).
2. Invoke ``pyinstaller`` per target with the right flags/excludes.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "src" / "shantytown" / "resources" / "icons" / "app_icon.svg"
ICO = ROOT / "build" / "app_icon.ico"
MAIN_ENTRY = ROOT / "src" / "shantytown" / "__main__.py"
HELPER_ENTRY = ROOT / "src" / "shantytown" / "loginhelper.py"
DIST = ROOT / "dist"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Modules dropped from the MAIN build so PyInstaller doesn't collect the
# QtWebEngine (~127 MB Chromium) payload or the code that needs it — that
# all lives in the separate helper exe. Excluding QtWebEngineCore stops
# its PyInstaller hook (which pulls in the binaries) from running.
_WEBVIEW_EXCLUDES = [
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineQuick",
    "shantytown.gui.webview_login_agent",
    "shantytown.loginhelper",
]

TARGETS = ("main", "helper")


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
    #   ICONDIRENTRY (16 bytes) x N: width, height, color count, reserved,
    #       planes, bit count, bytes_in_res, image_offset
    #   image data x N: each PNG blob
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


def build_exe(target: str) -> Path:
    """Drive PyInstaller for one ``target`` (``main`` / ``helper``).

    Both are ``--onefile``. ``main`` is windowed and excludes QtWebEngine;
    ``helper`` is a console app (clean stdio pipes) that includes it.
    Returns the output exe path.
    """
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        # Help the analyser find the package without an editable install.
        "--paths",
        "src",
    ]
    if target == "main":
        cmd += [
            "--windowed",
            "--name",
            "shantytown",
            "--icon",
            str(ICO),
            # Bundle the resources tree under the package's expected path so
            # ``Path(__file__).resolve().parents[1] / "resources"`` keeps
            # working at runtime.
            "--add-data",
            f"src/shantytown/resources{sep}shantytown/resources",
        ]
        for mod in _WEBVIEW_EXCLUDES:
            cmd += ["--exclude-module", mod]
        cmd.append(str(MAIN_ENTRY))
    else:  # helper — console app (clean stdio pipes), no custom icon
        cmd += ["--name", "__loginhelper", str(HELPER_ENTRY)]

    print(f"[build_exe:{target}] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    name = "shantytown" if target == "main" else "__loginhelper"
    out = DIST / f"{name}{exe_suffix}"
    print(f"[build_exe:{target}] {out}")
    return out


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024) if path.is_file() else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build shantytown exe(s).")
    parser.add_argument(
        "--target",
        choices=(*TARGETS, "both"),
        default="both",
        help="Which exe(s) to produce (default: both).",
    )
    args = parser.parse_args()
    targets = TARGETS if args.target == "both" else (args.target,)

    print("=== Building shantytown ===")
    build_ico()
    outputs = [build_exe(tgt) for tgt in targets]
    print()
    for out in outputs:
        print(f"Done: {out}  ({_size_mb(out):.0f} MB)")
    print("Ship shantytown.exe (+ __loginhelper.exe for webview login) "
          "together in one folder.")


if __name__ == "__main__":
    main()
