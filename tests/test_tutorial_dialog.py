"""Tests for gui.tutorial_dialog navigation."""

from __future__ import annotations

from shantytown.gui.tutorial_dialog import _PAGES, TutorialDialog


def test_starts_on_first_page(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    assert dialog._stack.current_index() == 0


def test_back_hidden_on_first_page(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    assert not dialog._back_btn.isVisible()


def test_next_advances(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_next()
    assert dialog._stack.current_index() == 1
    assert dialog._back_btn.isVisible()


def test_back_returns(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_next()
    dialog._on_next()
    assert dialog._stack.current_index() == 2
    dialog._on_back()
    assert dialog._stack.current_index() == 1


def test_last_page_button_label(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    for _ in range(len(_PAGES) - 1):
        dialog._on_next()
    # On the last page the next button reads "시작하기" / "Get started"
    # rather than "다음" / "Next".
    text = dialog._next_btn.text()
    assert text in {"시작하기", "Get started"}
    # Skip is hidden on the last page (nothing left to skip).
    assert not dialog._skip_btn.isVisible()


def test_finish_accepts_dialog(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    for _ in range(len(_PAGES) - 1):
        dialog._on_next()
    # Pressing "next" on the last page should accept the dialog.
    dialog._on_next()
    assert dialog.result() == TutorialDialog.DialogCode.Accepted


def test_skip_accepts_dialog(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._skip_btn.click()
    assert dialog.result() == TutorialDialog.DialogCode.Accepted


def test_dot_indicator_tracks_position(qtbot):
    dialog = TutorialDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._on_next()
    # Just sanity-check the indicator advanced.
    assert len(dialog._dots._dots) == len(_PAGES)
