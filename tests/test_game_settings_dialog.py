"""Tests for ``GameSettingsDialog`` async shortcut creation.

The actual PowerShell call is slow (1-3 s), so the dialog runs it on
a ``QThread`` and shows an indeterminate progress bar. These tests
cover the dispatch / state-restore / detach-on-close paths without
ever invoking a real subprocess — ``create_desktop_shortcut`` is
monkey-patched at the call site.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QMessageBox

from shantytown.core.models import InstalledGame
from shantytown.gui import game_settings_dialog as gsd_mod
from shantytown.gui.game_settings_dialog import GameSettingsDialog
from shantytown.store.games import GameStore


@pytest.fixture
def installed(tmp_path):
    install = tmp_path / "game"
    install.mkdir()
    return InstalledGame(
        product_id="tskx",
        install_path=install,
        game_type="GCL",
        version="1.0",
    )


@pytest.fixture
def game_store(tmp_path):
    return GameStore(tmp_path / "games.json")


def _open_dialog(qtbot, installed, game_store, monkeypatch):
    """Build the dialog, suppress the modal QMessageBox calls."""
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: 0)
    dialog = GameSettingsDialog(
        installed=installed, known=None, game_store=game_store
    )
    qtbot.addWidget(dialog)
    return dialog


def test_initial_progress_hidden(qtbot, installed, game_store, monkeypatch):
    """Idle state: button enabled with default label, progress hidden."""
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    assert dialog._shortcut_btn.isEnabled()
    assert not dialog._shortcut_spinner.isVisible()


def test_create_shortcut_kicks_off_async(
    qtbot, installed, game_store, monkeypatch, tmp_path
):
    """Clicking the button must not block — it disables the button,
    shows the spinner, and lets the worker run on its own."""
    fake_lnk = tmp_path / "Shortcut.lnk"
    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut",
        lambda **kw: fake_lnk,
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog.show()

    dialog._on_create_shortcut()

    # Synchronous post-conditions: in-flight UI applied immediately.
    assert not dialog._shortcut_btn.isEnabled()
    assert dialog._shortcut_spinner.isVisible()
    assert dialog._shortcut_thread is not None

    # On success the dialog accepts itself; track Accepted result.
    qtbot.waitUntil(lambda: dialog._shortcut_thread is None, timeout=2000)
    assert dialog.result() == dialog.DialogCode.Accepted


def test_create_shortcut_emits_signal_on_success(
    qtbot, installed, game_store, monkeypatch, tmp_path
):
    """The dialog hands the success message off via ``shortcut_created``
    so ``MainWindow`` can render the toast — no modal "success!" popup."""
    fake_lnk = tmp_path / "Shortcut.lnk"
    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut",
        lambda **kw: fake_lnk,
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog._name_input.setText("My Game")
    received: list[str] = []
    dialog.shortcut_created.connect(received.append)

    dialog._on_create_shortcut()
    qtbot.waitUntil(lambda: dialog._shortcut_thread is None, timeout=2000)

    assert len(received) == 1
    assert "My Game" in received[0]


def test_create_shortcut_failure_restores_ui(
    qtbot, installed, game_store, monkeypatch
):
    """Worker exception path: button comes back, progress hides, no
    crash. The warning dialog is mocked out so we don't need user input."""
    from shantytown.core.shortcuts import ShortcutError

    def _boom(**kw):
        raise ShortcutError("powershell not found")

    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut", _boom
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog.show()

    dialog._on_create_shortcut()
    qtbot.waitUntil(lambda: dialog._shortcut_thread is None, timeout=2000)
    assert dialog._shortcut_btn.isEnabled()
    assert not dialog._shortcut_spinner.isVisible()


def test_double_click_is_idempotent(
    qtbot, installed, game_store, monkeypatch, tmp_path
):
    """Two rapid clicks (e.g. before disable lands) must only spawn one
    worker — re-entrancy guard keeps a single thread per dialog."""
    fake_lnk = tmp_path / "x.lnk"
    started_count = 0

    def _slow(**kw):
        nonlocal started_count
        started_count += 1
        return fake_lnk

    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut", _slow
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog.show()

    dialog._on_create_shortcut()
    dialog._on_create_shortcut()  # second call must early-return

    qtbot.waitUntil(lambda: dialog._shortcut_thread is None, timeout=2000)
    assert started_count == 1


def test_close_during_creation_detaches_worker(
    qtbot, installed, game_store, monkeypatch
):
    """Closing the dialog while the worker is in flight must drop our
    refs and re-parent the thread so the QThread isn't destroyed
    mid-run when the dialog is GC'd.

    To keep the test fast and free of cross-thread cleanup races,
    ``_on_create_shortcut`` is monkeypatched at the dispatch level —
    we install fake thread/worker refs and verify ``done()`` clears
    them and re-parents the thread, no real subprocess involved."""
    from PyQt6.QtCore import QThread

    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)

    # Stand up a real but idle QThread (never started). Production code
    # only does ``setParent(None)`` and ``disconnect`` on these — both
    # work on an unstarted thread.
    fake_thread = QThread()
    fake_thread.setParent(dialog)
    fake_worker = gsd_mod._ShortcutWorker(
        name="x", product_id="tskx", icon_path=None
    )
    # The disconnect call in ``done()`` needs at least one matching
    # connection or it raises (which we catch, but the production path
    # makes the connection so let's mirror that here).
    fake_worker.finished.connect(dialog._on_shortcut_done)
    dialog._shortcut_thread = fake_thread
    dialog._shortcut_worker = fake_worker

    dialog.reject()

    assert dialog._shortcut_thread is None
    assert dialog._shortcut_worker is None
    assert fake_thread.parent() is None

    # Idle thread; safe to drop immediately.
    fake_thread.deleteLater()
    fake_worker.deleteLater()


def test_worker_run_emits_success(monkeypatch, tmp_path):
    """Pure-logic check on the worker — given a successful
    ``create_desktop_shortcut`` call, ``finished`` fires with
    ``(True, lnk_path, '')``."""
    fake_lnk = tmp_path / "ok.lnk"
    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut",
        lambda **kw: fake_lnk,
    )
    worker = gsd_mod._ShortcutWorker(
        name="x", product_id="tskx", icon_path=None
    )
    received: list[tuple[bool, str, str]] = []
    worker.finished.connect(lambda ok, lnk, err: received.append((ok, lnk, err)))
    worker.run()
    assert received == [(True, str(fake_lnk), "")]


def test_worker_run_emits_shortcut_error(monkeypatch):
    """Documented failure mode: ``ShortcutError`` is captured into the
    ``finished`` payload, not raised."""
    from shantytown.core.shortcuts import ShortcutError

    def _boom(**kw):
        raise ShortcutError("missing powershell")

    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut", _boom
    )
    worker = gsd_mod._ShortcutWorker(
        name="x", product_id="tskx", icon_path=None
    )
    received: list[tuple[bool, str, str]] = []
    worker.finished.connect(lambda ok, lnk, err: received.append((ok, lnk, err)))
    worker.run()
    assert received == [(False, "", "missing powershell")]


def test_worker_run_emits_unexpected_exception(monkeypatch):
    """Anything escaping ``ShortcutError`` (programming bug, OS oddity)
    must still flip the UI back — not propagate up the QThread and
    leave the dialog frozen."""

    def _boom(**kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(
        "shantytown.core.shortcuts.create_desktop_shortcut", _boom
    )
    worker = gsd_mod._ShortcutWorker(
        name="x", product_id="tskx", icon_path=None
    )
    received: list[tuple[bool, str, str]] = []
    worker.finished.connect(lambda ok, lnk, err: received.append((ok, lnk, err)))
    worker.run()
    assert received[0][0] is False
    assert "unexpected" in received[0][2]


def test_resolve_icon_path_prefers_live_input(
    qtbot, installed, game_store, monkeypatch, tmp_path
):
    """Live path field beats persisted config — user intent first."""
    persisted = tmp_path / "old.exe"
    persisted.write_bytes(b"")
    live = tmp_path / "new.exe"
    live.write_bytes(b"")
    from shantytown.store.games import GameConfig

    game_store.upsert(
        GameConfig(product_id=installed.product_id, exe_path=persisted)
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog._path_input.setText(str(live))
    assert dialog._resolve_icon_path() == live


def test_resolve_icon_path_falls_back_to_config(
    qtbot, installed, game_store, monkeypatch, tmp_path
):
    """No live input → persisted exe (if it exists)."""
    persisted = tmp_path / "x.exe"
    persisted.write_bytes(b"")
    from shantytown.store.games import GameConfig

    game_store.upsert(
        GameConfig(product_id=installed.product_id, exe_path=persisted)
    )
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog._path_input.setText("")
    assert dialog._resolve_icon_path() == persisted


def test_resolve_icon_path_returns_none_when_nothing_resolves(
    qtbot, installed, game_store, monkeypatch
):
    """Neither live nor persisted exists → ``None`` so the shortcuts
    module knows to fall back to Shantytown's own icon."""
    dialog = _open_dialog(qtbot, installed, game_store, monkeypatch)
    dialog._path_input.setText("/no/such/file.exe")
    assert dialog._resolve_icon_path() is None
