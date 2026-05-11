"""Tests for gui.main_window — card rendering and state derivation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shantytown.core.api import DmmApiClient
from shantytown.gui.game_card import CardState, GameCard, compute_state
from shantytown.gui.main_window import MainWindow
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.profiles import ProfileStore

FIXTURE_CNF = Path(__file__).parent / "fixtures" / "dmmgame.cnf.sample"


def _all_cards(window: MainWindow) -> list[GameCard]:
    cards: list[GameCard] = []
    for i in range(window._grid.count()):
        item = window._grid.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if isinstance(w, GameCard):
            cards.append(w)
    return cards


@pytest.fixture
def fresh_stores(tmp_path):
    profile_store = ProfileStore(tmp_path / "profiles.json")
    game_store = GameStore(tmp_path / "games.json")
    return profile_store, game_store


def test_renders_one_card_per_installed_game(qtbot, fresh_stores):
    profile_store, game_store = fresh_stores
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    cards = _all_cards(window)
    assert len(cards) == 5
    assert {c.product_id for c in cards} == {
        "tskx",
        "muv_luv_girlsgardenx_cl",
        "dotabyss_x_cl",
        "girlscreation_r",
        "rlyehshoujotaix_cl",
    }


def test_unconfigured_card_shows_setup_status(qtbot, fresh_stores):
    profile_store, game_store = fresh_stores
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    for c in _all_cards(window):
        assert c._status_label.text() == "설정 필요"


def test_card_uses_known_games_display_name(qtbot, fresh_stores):
    profile_store, game_store = fresh_stores
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    tskx_card = next(c for c in _all_cards(window) if c.product_id == "tskx")
    assert "Twinkle" in tskx_card._title.text()


def test_configured_with_token_shows_ready(qtbot, fresh_stores, tmp_path):
    profile_store, game_store = fresh_stores
    profile_store.create("alice", token="tok-abc")
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))

    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    tskx = next(c for c in _all_cards(window) if c.product_id == "tskx")
    assert tskx._status_label.text() == "실행"


def test_configured_without_token_shows_login_required(
    qtbot, fresh_stores, tmp_path
):
    profile_store, game_store = fresh_stores
    profile_store.create("alice")  # no token
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_bytes(b"")
    game_store.upsert(GameConfig(product_id="tskx", exe_path=fake_exe))

    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    tskx = next(c for c in _all_cards(window) if c.product_id == "tskx")
    assert tskx._status_label.text() == "로그인 필요"


def test_missing_cnf_yields_empty_grid(qtbot, fresh_stores, tmp_path, monkeypatch):
    profile_store, game_store = fresh_stores
    api = MagicMock(spec=DmmApiClient)

    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: 0)

    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=tmp_path / "does-not-exist.cnf",
    )
    qtbot.addWidget(window)
    assert _all_cards(window) == []


# --- compute_state pure tests ---


def _make_cfg(exe_path):
    return GameConfig(product_id="x", exe_path=exe_path)


def test_compute_state_running_takes_priority(tmp_path):
    exe = tmp_path / "g.exe"
    exe.write_bytes(b"")
    cfg = _make_cfg(exe)
    state = compute_state(cfg, bound_profile=None, is_running=True)
    assert state is CardState.RUNNING


def test_compute_state_no_config_is_setup_needed():
    state = compute_state(None, bound_profile=None, is_running=False)
    assert state is CardState.NEEDS_SETUP


def test_compute_state_config_without_exe_is_setup_needed():
    cfg = GameConfig(product_id="x", exe_path=None)
    state = compute_state(cfg, bound_profile=None, is_running=False)
    assert state is CardState.NEEDS_SETUP


def test_compute_state_no_token_is_login_required(tmp_path):
    from datetime import UTC, datetime

    from shantytown.store.profiles import Profile

    exe = tmp_path / "g.exe"
    exe.write_bytes(b"")
    profile = Profile(
        id="p", name="alice", token=None, created_at=datetime.now(UTC)
    )
    state = compute_state(_make_cfg(exe), bound_profile=profile, is_running=False)
    assert state is CardState.NEEDS_LOGIN


def test_show_toast_spawns_toast_widget(qtbot, fresh_stores):
    """``MainWindow.show_toast`` plants a ``Toast`` on the central widget
    so the slide-down lives inside the main window's z-stack."""
    from shantytown.gui.toast import Toast

    profile_store, game_store = fresh_stores
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    window.show()

    window.show_toast("Saved!")

    central = window.centralWidget()
    assert central is not None
    toasts = [c for c in central.findChildren(Toast)]
    assert len(toasts) == 1


def test_compute_state_with_token_is_ready(tmp_path):
    from datetime import UTC, datetime

    from shantytown.store.profiles import Profile

    exe = tmp_path / "g.exe"
    exe.write_bytes(b"")
    profile = Profile(
        id="p", name="alice", token="tok", created_at=datetime.now(UTC)
    )
    state = compute_state(_make_cfg(exe), bound_profile=profile, is_running=False)
    assert state is CardState.READY
