"""Tiny indeterminate spinner widget.

Standalone — no QMovie asset, no third-party dep, ~70 lines. Draws
a partial arc whose angle is driven by ``QVariantAnimation`` so the
rotation interpolates continuously rather than jumping in fixed
``QTimer`` ticks. The animation framework drives at Qt's compositor-
synced rate (~60 fps default), which on high-refresh-rate displays
reads as smooth motion instead of the visible 16-fps "stutter" a
60-ms ``QTimer`` produces.

The animation only runs while the widget is visible: ``showEvent``
/ ``hideEvent`` start and stop it. Costs nothing to leave hidden in
a layout, which is the typical "show during async work" usage.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PyQt6.QtGui import QHideEvent, QPainter, QPaintEvent, QPalette, QPen, QShowEvent
from PyQt6.QtWidgets import QWidget

# One full rotation in 1.2 s. Slow enough to look intentional, fast
# enough to read as "actively working". Tweak here if the spinner
# ever starts feeling sluggish or frantic relative to surrounding UI.
_ROTATION_PERIOD_MS = 1200

# Stroke width for the arc. 2 px reads cleanly at the 18-24 px sizes
# we use for inline spinners.
_STROKE_PX = 2

# Sweep length: how much of the 360° circle the visible arc covers.
# 270° leaves a gap that makes the rotation obvious; a full ring
# would look static no matter how fast it spins.
_SWEEP_DEG = 270


class Spinner(QWidget):
    """Indeterminate "I'm working" indicator. Rotating arc."""

    def __init__(self, size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        # Float so the animation framework's per-frame interpolation
        # gives sub-degree precision — the arc moves a little each
        # paint instead of jumping in 30° steps.
        self._angle: float = 0.0

        # ``QVariantAnimation`` runs on Qt's unified animation timer,
        # which targets the screen refresh rate (60 fps default, more
        # on high-Hz monitors when the platform's animation driver
        # supports it). Linear easing keeps angular velocity constant.
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(_ROTATION_PERIOD_MS)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._on_angle_changed)

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        self._anim.start()

    def hideEvent(self, event: QHideEvent | None) -> None:
        super().hideEvent(event)
        self._anim.stop()

    def _on_angle_changed(self, value: object) -> None:
        # ``valueChanged`` carries a QVariant; we set float endpoints
        # so it round-trips as ``float`` here. Defensive cast guards
        # against the rare case where Qt hands us an int.
        self._angle = float(value) if isinstance(value, int | float) else 0.0
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        pen = QPen(color)
        pen.setWidth(_STROKE_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # Inset so the stroke doesn't clip on the edge of the widget.
        margin = _STROKE_PX
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        # Qt's drawArc takes 1/16-degree integer units. Negative
        # direction so the arc spins clockwise — matches every other
        # Windows/macOS spinner the user has ever seen.
        painter.drawArc(rect, int(-self._angle * 16), -_SWEEP_DEG * 16)
        painter.end()
