"""Tests for the slide-down Toast widget.

The animation timing is deferred to Qt's event loop in production,
which makes precise frame-by-frame assertions flaky. We pin the
contract that matters: positioning, the dwell-then-dismiss flow, and
self-cleanup via ``deleteLater``.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QWidget

from shantytown.gui.toast import (
    DWELL_MS,
    SLIDE_MS,
    TOP_MARGIN_PX,
    Toast,
)


def _make_parent(qtbot, width: int = 800, height: int = 600) -> QWidget:
    parent = QWidget()
    parent.resize(width, height)
    qtbot.addWidget(parent)
    return parent


def test_toast_positions_above_parent_initially(qtbot):
    """Before the slide-in animation starts, the toast sits above the
    parent's visible area (negative y) so it can slide down into view."""
    parent = _make_parent(qtbot)
    parent.show()
    qtbot.waitExposed(parent)
    toast = Toast(parent, "Hello")
    toast.show_animated()
    # Animation duration is short; sample state once which captures the
    # starting position before any tick has progressed it noticeably.
    assert toast.y() <= 0  # never lower than 0 at start


def test_toast_centers_horizontally(qtbot):
    parent = _make_parent(qtbot, width=1000)
    parent.show()
    qtbot.waitExposed(parent)
    toast = Toast(parent, "Hi")
    toast.show_animated()
    # Centre tolerance — adjustSize gives the toast a dynamic width.
    expected_x = (parent.width() - toast.width()) // 2
    assert abs(toast.x() - expected_x) <= 1


def test_toast_settles_at_top_margin_after_slide_in(qtbot):
    parent = _make_parent(qtbot)
    parent.show()
    qtbot.waitExposed(parent)
    toast = Toast(parent, "Done")
    toast.show_animated()
    # Slide-in animation completes within SLIDE_MS; +50 ms slack for
    # the qtbot event loop to actually run the tween.
    qtbot.waitUntil(
        lambda: toast.pos() == QPoint(toast.x(), TOP_MARGIN_PX),
        timeout=SLIDE_MS + 200,
    )


def test_toast_dismisses_after_dwell(qtbot):
    """Full lifecycle: slide-in, dwell, slide-out, deleteLater."""
    parent = _make_parent(qtbot)
    parent.show()
    qtbot.waitExposed(parent)
    toast = Toast(parent, "Saved")
    destroyed: list[bool] = []
    toast.destroyed.connect(lambda _o=None: destroyed.append(True))
    toast.show_animated()
    # SLIDE_MS in + DWELL_MS dwell + SLIDE_MS out + cleanup slack.
    timeout = SLIDE_MS * 2 + DWELL_MS + 500
    qtbot.waitUntil(lambda: bool(destroyed), timeout=timeout)


def test_toast_is_transparent_for_mouse_events(qtbot):
    """The toast is purely a status indicator — clicks must reach the
    UI underneath, not get swallowed by the floating green pill."""
    from PyQt6.QtCore import Qt

    parent = _make_parent(qtbot)
    toast = Toast(parent, "x")
    assert toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_toast_with_orphan_parent_falls_back_to_show(qtbot):
    """Defensive: if somehow constructed without a parent (which Python
    type system allows even if the API hints discourage it), show()
    is called instead of crashing on ``parent.width()``."""
    # We can't construct a Toast with parent=None directly because
    # QFrame requires a QWidget* — but we can simulate the no-parent
    # branch by hiding the parent before show_animated. The branch
    # is covered when ``parentWidget()`` returns None (e.g., after
    # ``setParent(None)``).
    parent = _make_parent(qtbot)
    toast = Toast(parent, "x")
    toast.setParent(None)  # type: ignore[arg-type]
    qtbot.addWidget(toast)
    toast.show_animated()
    # Just ensure no exception and the widget reports visible.
    assert toast.isVisible()
