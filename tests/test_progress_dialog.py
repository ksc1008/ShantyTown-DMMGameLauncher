"""Tests for gui.progress_dialog — failure UI and the logout action."""

from __future__ import annotations

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton

from shantytown.core.i18n import t
from shantytown.gui.progress_dialog import ProgressDialog


def _logout_button(dialog: ProgressDialog) -> QPushButton | None:
    for btn in dialog._buttons.buttons():
        if btn.text() == t("progress.logout_button"):
            return btn
    return None


def test_failure_without_logout_shows_only_close(qtbot):
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    dialog.finish(False, "boom")

    assert _logout_button(dialog) is None
    close = dialog._buttons.button(QDialogButtonBox.StandardButton.Close)
    assert close is not None


def test_enable_logout_adds_button_on_failure(qtbot):
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    dialog.enable_logout(lambda: None)
    dialog.finish(False, "auth boom")

    assert _logout_button(dialog) is not None


def test_logout_not_shown_on_success(qtbot):
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    dialog.enable_logout(lambda: None)
    dialog.finish(True, "ok")

    assert _logout_button(dialog) is None


def test_clicking_logout_runs_callback_and_closes(qtbot):
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    calls: list[int] = []
    dialog.enable_logout(lambda: calls.append(1))
    dialog.finish(False, "auth boom")

    btn = _logout_button(dialog)
    assert btn is not None

    with qtbot.waitSignal(dialog.rejected):
        btn.click()

    assert calls == [1]
