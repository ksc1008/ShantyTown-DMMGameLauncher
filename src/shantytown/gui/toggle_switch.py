"""A small iOS-style on/off toggle switch.

``QCheckBox`` styled as a switch never looks quite right across themes,
so this is a purpose-built checkable button that paints a pill track and
a sliding knob. It reads its "off" colors from the active palette so it
sits correctly on both light and dark themes, and uses the app's muted
blue for the "on" state to match the primary buttons elsewhere.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPalette
from PyQt6.QtWidgets import QAbstractButton, QWidget

# Muted blue — matches the primary buttons in the profile/login dialogs.
_ON_COLOR = "#4a73c2"


class ToggleSwitch(QAbstractButton):
    """Checkable pill switch. ``toggled(bool)`` fires on state change."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._track_w = 44
        self._track_h = 24
        self._margin = 3
        self.setFixedSize(self._track_w, self._track_h)

    def sizeHint(self) -> QSize:
        return QSize(self._track_w, self._track_h)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        checked = self.isChecked()
        enabled = self.isEnabled()

        # Track.
        if checked:
            track = QColor(_ON_COLOR)
        else:
            track = self.palette().color(QPalette.ColorRole.Mid)
        if not enabled:
            track.setAlpha(120)
        painter.setBrush(track)
        radius = self._track_h / 2
        painter.drawRoundedRect(
            0, 0, self._track_w, self._track_h, radius, radius
        )

        # Knob.
        knob_d = self._track_h - 2 * self._margin
        x = (
            self._track_w - knob_d - self._margin
            if checked
            else self._margin
        )
        knob = QColor("white")
        if not enabled:
            knob.setAlpha(180)
        painter.setBrush(knob)
        painter.drawEllipse(int(x), self._margin, knob_d, knob_d)
