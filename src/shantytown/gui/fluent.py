"""Fluent Design tokens for our theme.

The QPalette set in ``theme.py`` covers the broad strokes (window /
text / accent), but card surfaces, state colors, and hover tints need
their own theme-aware token table — Qt's palette doesn't have slots
for "light-green hover overlay" or "Fluent border."

Tokens here intentionally mirror Microsoft's Fluent Design:

- ``surface`` is the elevated layer that sits *above* the window's
  base color. Cards use it so they read as physical surfaces, not
  bleed into the background.
- ``surface_hover_*`` are the states-as-tint variants, ~8% opacity
  effective tint over the base surface. They keep the layered look
  while signaling the action that's about to happen.
- ``state_*`` colors are for the small status caption (실행 / 로그인
  필요 / …) — bold but not garish.

To pick which set applies, ``current_tokens(widget)`` reads the active
palette's ``Window`` luminance: dark window → dark tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True)
class FluentTokens:
    surface: str
    surface_border: str
    surface_hover_setup: str
    surface_hover_ready: str
    surface_hover_login: str
    state_ready: str
    state_login: str
    state_running: str
    state_setup: str
    icon_placeholder: str
    accent: str


LIGHT_TOKENS = FluentTokens(
    surface="#ffffff",
    surface_border="#e5e5e5",
    surface_hover_setup="#f4f4f4",
    surface_hover_ready="#eef7ee",
    surface_hover_login="#fbf3e3",
    state_ready="#107c10",  # Fluent green-100
    state_login="#9e6600",  # Fluent amber-200
    state_running="#605e5c",  # neutral foreground
    state_setup="#605e5c",
    icon_placeholder="#8a8886",
    accent="#0067c0",
)

DARK_TOKENS = FluentTokens(
    surface="#2b2b2b",
    surface_border="#3a3a3a",
    surface_hover_setup="#333333",
    surface_hover_ready="#293a29",
    surface_hover_login="#3b3026",
    state_ready="#6cc46c",
    state_login="#fbb049",
    state_running="#c8c6c4",
    state_setup="#c8c6c4",
    icon_placeholder="#a19f9d",
    accent="#4cc2ff",
)


def current_tokens(widget: QWidget) -> FluentTokens:
    """Pick light/dark tokens by inspecting the widget's palette."""
    bg = widget.palette().color(QPalette.ColorRole.Window)
    return DARK_TOKENS if bg.lightness() < 128 else LIGHT_TOKENS
