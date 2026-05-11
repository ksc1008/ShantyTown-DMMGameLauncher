"""Tests for the Spinner widget.

The widget is mostly QPainter — tested indirectly here. We pin the
visible-only-while-shown contract because callers rely on it (drop
a hidden Spinner in a layout, no animation cost).
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractAnimation

from shantytown.gui.spinner import Spinner


def test_spinner_starts_hidden_with_animation_stopped(qtbot):
    spinner = Spinner()
    qtbot.addWidget(spinner)
    assert spinner._anim.state() == QAbstractAnimation.State.Stopped


def test_spinner_starts_animation_on_show(qtbot):
    spinner = Spinner()
    qtbot.addWidget(spinner)
    spinner.show()
    qtbot.waitExposed(spinner)
    assert spinner._anim.state() == QAbstractAnimation.State.Running


def test_spinner_stops_animation_on_hide(qtbot):
    spinner = Spinner()
    qtbot.addWidget(spinner)
    spinner.show()
    qtbot.waitExposed(spinner)
    spinner.hide()
    assert spinner._anim.state() == QAbstractAnimation.State.Stopped


def test_spinner_advances_angle_during_animation(qtbot):
    """Once running, the angle must change continuously — pre-condition
    for smooth rotation. We sample twice across a short wait."""
    spinner = Spinner()
    qtbot.addWidget(spinner)
    spinner.show()
    qtbot.waitExposed(spinner)
    before = spinner._angle
    qtbot.wait(120)
    assert spinner._angle != before


def test_spinner_loops_indefinitely(qtbot):
    """Animation must be configured to loop forever, not stop after
    one rotation."""
    spinner = Spinner()
    qtbot.addWidget(spinner)
    assert spinner._anim.loopCount() == -1


def test_spinner_value_changed_handler_accepts_floats(qtbot):
    """``QVariantAnimation`` may pass either ``int`` or ``float`` —
    the slot must read the value safely without TypeError."""
    spinner = Spinner()
    qtbot.addWidget(spinner)
    spinner._on_angle_changed(45.5)
    assert spinner._angle == 45.5
    spinner._on_angle_changed(180)
    assert spinner._angle == 180.0
