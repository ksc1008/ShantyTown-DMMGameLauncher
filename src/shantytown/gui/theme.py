"""Theme application aligned to Fluent Design.

Three modes:

- **system**: follow the OS color scheme on Qt 6.5+ (``QStyleHints.colorScheme``).
  Older Qt builds fall back to the light palette.
- **light**: Fluent-tone light palette (`#f3f3f3` window, `#ffffff` surface).
- **dark**: Fluent-tone dark palette (`#202020` window, `#2b2b2b` surface).

We force Fusion + the explicit palette for non-system modes so the
tokens render the same on Windows / macOS / Linux. In system mode we
let Qt's own style win (modulo the OS dark/light hint).
"""

from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

ThemeMode = Literal["system", "light", "dark"]


def _light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#f3f3f3"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#202020"))
    p.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#fafafa"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#202020"))
    p.setColor(QPalette.ColorRole.Text, QColor("#202020"))
    p.setColor(QPalette.ColorRole.Button, QColor("#fbfbfb"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#202020"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#c42b1c"))
    p.setColor(QPalette.ColorRole.Link, QColor("#0067c0"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#0067c0"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8886"))
    p.setColor(QPalette.ColorRole.Mid, QColor("#d1d1d1"))
    p.setColor(QPalette.ColorRole.Midlight, QColor("#ebebeb"))
    return p


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Base, QColor("#2b2b2b"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#323232"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2b2b"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.Button, QColor("#2b2b2b"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#ff99a4"))
    p.setColor(QPalette.ColorRole.Link, QColor("#4cc2ff"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#4cc2ff"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#a19f9d"))
    p.setColor(QPalette.ColorRole.Mid, QColor("#3a3a3a"))
    p.setColor(QPalette.ColorRole.Midlight, QColor("#333333"))
    return p


def _set_color_scheme(app: QApplication, scheme: Qt.ColorScheme | None) -> None:
    """Push the chosen color scheme into ``QStyleHints``.

    Some widgets (esp. on Qt 6.5+ with the new dark-mode aware styling)
    consult ``QStyleHints.colorScheme()`` directly, separately from the
    palette. Without this call, an explicit ``"dark"`` request on a
    light OS produces "inverted" widgets — title bars and group
    backgrounds keep using the OS-derived light scheme even though we
    set a dark palette. ``setColorScheme`` (Qt 6.8+) lets us override.

    ``scheme=None`` revives the OS-detected default via
    ``unsetColorScheme``.
    """
    hints = app.styleHints()
    if hints is None:
        return
    try:
        if scheme is None:
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(scheme)
    except (AttributeError, RuntimeError):
        # Older Qt without setColorScheme — palette alone has to suffice.
        pass


def _rebroadcast_stylesheet(app: QApplication) -> None:
    """Force the app stylesheet to re-resolve ``palette(...)`` references.

    Qt's QSS engine caches resolved palette colors per stylesheet rule.
    A bare ``app.setPalette(...)`` updates widget palettes but does NOT
    invalidate stylesheet rules that reference ``palette(button)`` etc.
    Setting the stylesheet to empty and re-setting it triggers a full
    re-parse, which finally evaluates the palette refs against the new
    palette. Without this, switching to dark mode leaves toolbar
    buttons / headers / containers rendering with the previous (light)
    palette colors — the "opposite theme" symptom.
    """
    ss = app.styleSheet()
    if not ss:
        return
    app.setStyleSheet("")
    app.setStyleSheet(ss)


def apply_theme(app: QApplication, mode: ThemeMode) -> None:
    """Apply ``mode`` to ``app``. Idempotent."""
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    if mode == "system":
        # Hand the color scheme back to the OS, then mirror its choice
        # in our palette so non-stylesheet widgets stay consistent.
        _set_color_scheme(app, None)
        try:
            hints = app.styleHints()
            scheme = hints.colorScheme() if hints is not None else None
            if scheme == Qt.ColorScheme.Dark:
                app.setPalette(_dark_palette())
            else:
                app.setPalette(_light_palette())
        except (AttributeError, RuntimeError):
            app.setPalette(_light_palette())
        _rebroadcast_stylesheet(app)
        return

    target_scheme = Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light
    _set_color_scheme(app, target_scheme)
    app.setPalette(_dark_palette() if mode == "dark" else _light_palette())
    _rebroadcast_stylesheet(app)
