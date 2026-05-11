"""Brief slide-down toast notification.

Positive variant only for now — a green pill that slides down from
the top of its parent widget, dwells for ~2 seconds, then slides
back up and self-deletes. Designed to replace modal "success!"
QMessageBox dialogs which are noisy for low-importance feedback.

Parented to a normal widget (typically the main window's central
widget) rather than spawning a top-level window — that keeps the
toast on the same z-stack as the rest of the UI and avoids the
"taskbar flash" you get with frameless top-levels on Windows.

Usage:

    Toast(parent_widget, "Saved!").show_animated()

The caller doesn't need to hold the reference; Qt's parent ownership
plus the exit-animation ``deleteLater`` keep the lifecycle tight.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

# Slide animation duration. 220 ms is the sweet spot for "snappy but
# noticeable" — fast enough that the user reads it as immediate
# feedback, slow enough that the motion registers as intentional.
SLIDE_MS = 220
# How long the toast stays put after sliding in. Must comfortably
# cover the time it takes to read a short message; 2.2 s is enough
# for ~5-7 words at typical reading speed.
DWELL_MS = 2200
# Distance from the top of the parent. 12 px reads as "floating just
# below the chrome" without colliding with anything in the layout.
TOP_MARGIN_PX = 12
# Cap to keep long messages from sprawling across wide windows.
MAX_WIDTH_PX = 480

# ``#10b981`` is the same emerald used for the "step done" badge in
# the login dialog — keeps the success-green consistent across the UI.
_POSITIVE_QSS = """
QFrame#toast {
    background-color: #10b981;
    border-radius: 8px;
}
QLabel#toast_label {
    color: white;
    font-weight: 600;
    padding: 10px 18px;
}
"""


class Toast(QFrame):
    """Slide-down positive notification."""

    def __init__(self, parent: QWidget, message: str) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet(_POSITIVE_QSS)
        # Pass through input — the toast is a status indicator, not an
        # interactive element, and shouldn't intercept clicks meant
        # for the UI it's floating over.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(message)
        label.setObjectName("toast_label")
        layout.addWidget(label)
        self.setMaximumWidth(MAX_WIDTH_PX)
        self.adjustSize()

        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(SLIDE_MS)

        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.setInterval(DWELL_MS)
        self._dwell.timeout.connect(self._slide_out)

    def show_animated(self) -> None:
        """Position above the parent's top edge, slide down, dwell, slide up."""
        parent = self.parentWidget()
        if parent is None:
            self.show()
            return
        self.adjustSize()
        x = max(0, (parent.width() - self.width()) // 2)
        start = QPoint(x, -self.height())
        end = QPoint(x, TOP_MARGIN_PX)
        self.move(start)
        self.show()
        # Z-order: pop above any siblings (cards, scroll area, etc.)
        # — the toast must not get clipped by content widgets.
        self.raise_()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reset_anim_finished(self._dwell.start)
        self._anim.start()

    def _slide_out(self) -> None:
        x = self.x()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(x, -self.height()))
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._reset_anim_finished(self._dismiss)
        self._anim.start()

    def _dismiss(self) -> None:
        self.hide()
        self.deleteLater()

    def _reset_anim_finished(self, slot: Callable[[], None]) -> None:
        # The same QPropertyAnimation drives both slide-in and slide-out;
        # the slide-in's ``finished`` slot must not still be wired when
        # we re-arm for slide-out (otherwise the dwell timer fires twice
        # and the toast bounces).
        try:
            self._anim.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._anim.finished.connect(slot)
