"""Tests for ``MainWindow.begin_silent_launch`` / ``handle_external_launch``.

The ``--launch=<id>`` flag boots the app into "shortcut mode": main
window stays hidden, the launch flow runs through the progress dialog
only, and on clean success we quit without the user ever seeing the
launcher chrome.

These tests exercise the dispatch matrix — what each combination of
(installed?, running?, configured?, has_token?) does — without
spinning up an actual launch worker. The worker is mocked at the
``_launch_game`` boundary so we don't need network or threads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shantytown.core.api import DmmApiClient
from shantytown.gui.main_window import MainWindow, _RunningGame
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.profiles import ProfileStore

FIXTURE_CNF = Path(__file__).parent / "fixtures" / "dmmgame.cnf.sample"


@pytest.fixture
def fresh_stores(tmp_path):
    return (
        ProfileStore(tmp_path / "profiles.json"),
        GameStore(tmp_path / "games.json"),
    )


def _make_window(qtbot, profile_store, game_store):
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    return window


def test_silent_launch_not_installed_shows_window(
    qtbot, fresh_stores, monkeypatch
):
    """A shortcut for a product_id that's no longer in dmmgame.cnf
    should reveal the main window with a warning, not silently die."""
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)

    warned: list[tuple[str, str]] = []
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, body, *a, **kw: warned.append((title, body)),
    )

    window.begin_silent_launch("not-a-real-id")

    assert window.isVisible()
    assert window._silent_mode is False
    assert len(warned) == 1
    assert "not-a-real-id" in warned[0][1]


def test_silent_launch_already_running_quits(
    qtbot, fresh_stores, monkeypatch
):
    """If the game's already running, the spec says do nothing —
    quit the launcher process without surfacing UI."""
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)

    # Inject a running entry without spawning a real process.
    window._running["tskx"] = _RunningGame(pid=99999)

    quit_calls: list[bool] = []
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))

    window.begin_silent_launch("tskx")

    assert quit_calls == [True]
    assert not window.isVisible()
    assert window._silent_mode is False


def test_silent_launch_needs_setup_shows_window(
    qtbot, fresh_stores, monkeypatch
):
    """Game in cnf but no exe configured → reveal window and dispatch
    through the same path as a card click so the user resolves it
    with the full UI in front of them."""
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)

    clicked: list[str] = []
    monkeypatch.setattr(window, "_on_status_clicked", clicked.append)

    window.begin_silent_launch("tskx")

    assert window.isVisible()
    assert window._silent_mode is False
    assert clicked == ["tskx"]


def test_silent_launch_needs_login_shows_window(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    profile_store, game_store = fresh_stores
    profile_store.create("alice")  # no token
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))
    window = _make_window(qtbot, profile_store, game_store)

    clicked: list[str] = []
    monkeypatch.setattr(window, "_on_status_clicked", clicked.append)

    window.begin_silent_launch("tskx")

    assert window.isVisible()
    assert clicked == ["tskx"]


def test_silent_launch_ready_runs_launch_worker(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """Fully configured + token present → drive ``_launch_game`` without
    revealing the main window. The progress dialog handles its own UI."""
    profile_store, game_store = fresh_stores
    profile_store.create("alice", token="tok-abc")
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))
    window = _make_window(qtbot, profile_store, game_store)

    launched: list[str] = []
    monkeypatch.setattr(window, "_launch_game", launched.append)

    window.begin_silent_launch("tskx")

    assert launched == ["tskx"]
    assert window._silent_mode is True
    # MainWindow itself stays hidden — the progress dialog (which we
    # mocked out via ``_launch_game``) would be the only visible window.
    assert not window.isVisible()


def test_silent_success_quits_app_when_window_hidden(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """``_on_launch_finished`` with success and silent_mode + hidden
    window must call ``QApplication.quit()`` so the launcher exits."""
    profile_store, game_store = fresh_stores
    profile = profile_store.create("alice", token="tok-abc")
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))
    window = _make_window(qtbot, profile_store, game_store)

    window._silent_mode = True
    quit_calls: list[bool] = []
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))

    cfg = GameConfig(product_id="tskx", exe_path=fake_exe)
    # popen=None: simulates a launch that succeeded but produced no
    # subprocess to track (real flow always returns a Popen, but the
    # quit decision shouldn't depend on that).
    window._on_launch_finished(
        success=True,
        message="ok",
        popen=None,
        product_id="tskx",
        profile=profile,
        cfg=cfg,
    )

    assert quit_calls == [True]
    assert window._silent_mode is False


def test_silent_failure_reveals_window(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """When silent launch fails (worker error), the main window must
    appear so the user has somewhere to go."""
    profile_store, game_store = fresh_stores
    profile = profile_store.create("alice", token="tok-abc")
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))
    window = _make_window(qtbot, profile_store, game_store)

    window._silent_mode = True
    cfg = GameConfig(product_id="tskx", exe_path=fake_exe)
    window._on_launch_finished(
        success=False,
        message="something broke",
        popen=None,
        product_id="tskx",
        profile=profile,
        cfg=cfg,
    )

    assert window.isVisible()
    assert window._silent_mode is False


def test_handle_external_launch_dispatches(
    qtbot, fresh_stores, monkeypatch
):
    """An IPC ``launch:<id>`` from a second invocation runs through
    the click handler — the user is already engaged with this
    instance, so no silent path."""
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)

    clicked: list[str] = []
    monkeypatch.setattr(window, "_on_status_clicked", clicked.append)

    window.handle_external_launch("tskx")

    assert clicked == ["tskx"]


def test_handle_external_launch_running_is_noop(
    qtbot, fresh_stores, monkeypatch
):
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)
    window._running["tskx"] = _RunningGame(pid=99999)

    clicked: list[str] = []
    monkeypatch.setattr(window, "_on_status_clicked", clicked.append)

    window.handle_external_launch("tskx")

    assert clicked == []


def test_handle_external_launch_not_installed_warns(
    qtbot, fresh_stores, monkeypatch
):
    profile_store, game_store = fresh_stores
    window = _make_window(qtbot, profile_store, game_store)

    warned: list[tuple[str, str]] = []
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, body, *a, **kw: warned.append((title, body)),
    )

    window.handle_external_launch("not-installed")

    assert len(warned) == 1
    assert "not-installed" in warned[0][1]
