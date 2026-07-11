"""Tests for gui.main_window — card rendering and state derivation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import shantytown.gui.main_window as mw
from shantytown.core.api import DmmApiClient
from shantytown.gui.game_card import CardState, GameCard, compute_state
from shantytown.gui.main_window import MainWindow
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.profiles import ProfileStore
from shantytown.store.settings import Settings, SettingsStore

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


def test_logout_from_launch_clears_token_and_toasts(qtbot, fresh_stores):
    """The launch-error logout action wipes the profile token and shows
    a confirmation toast so a re-launch routes through the login flow."""
    from shantytown.gui.toast import Toast

    profile_store, game_store = fresh_stores
    profile = profile_store.create("alice", token="live-token")
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    window.show()

    window._logout_from_launch(profile, "tskx")

    reloaded = profile_store.get(profile.id)
    assert reloaded is not None
    assert reloaded.token is None

    central = window.centralWidget()
    assert central is not None
    assert len(central.findChildren(Toast)) == 1


def test_logout_from_launch_tolerates_missing_profile(qtbot, fresh_stores):
    """A profile deleted between launch start and the logout click must
    not raise — the handler no-ops the store write and still toasts."""
    from datetime import UTC, datetime

    from shantytown.store.profiles import Profile

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

    ghost = Profile(
        id="gone", name="ghost", token="tok", created_at=datetime.now(UTC)
    )
    window._logout_from_launch(ghost, "tskx")  # must not raise


class _FakeWebDialog:
    instances = 0

    def __init__(self, *_args, **_kwargs) -> None:
        _FakeWebDialog.instances += 1
        # The webview branch connects to this signal.
        self.login_requested = MagicMock()

    def exec(self) -> int:
        return 0


class _FakeBrowserDialog:
    instances = 0

    def __init__(self, *_args, **_kwargs) -> None:
        _FakeBrowserDialog.instances += 1
        self.token_issued = MagicMock()

    def exec(self) -> int:
        return 0


def _login_flow_window(fresh_stores, tmp_path, method):
    profile_store, game_store = fresh_stores
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method=method))
    profile = profile_store.create("alice")
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        settings_store=settings,
        cnf_path=FIXTURE_CNF,
    )
    return window, profile


def test_login_then_launch_uses_webview_dialog_when_method_webview(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    # Helper is available in dev, so webview is honoured (no --debug needed).
    _FakeWebDialog.instances = 0
    _FakeBrowserDialog.instances = 0
    monkeypatch.setattr(mw, "WebLoginDialog", _FakeWebDialog)
    monkeypatch.setattr(mw, "LoginDialog", _FakeBrowserDialog)

    window, profile = _login_flow_window(fresh_stores, tmp_path, "webview")
    qtbot.addWidget(window)
    window._login_then_launch(profile, "tskx")

    assert _FakeWebDialog.instances == 1
    assert _FakeBrowserDialog.instances == 0


def test_login_then_launch_uses_browser_dialog_when_method_browser(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    _FakeWebDialog.instances = 0
    _FakeBrowserDialog.instances = 0
    monkeypatch.setattr(mw, "WebLoginDialog", _FakeWebDialog)
    monkeypatch.setattr(mw, "LoginDialog", _FakeBrowserDialog)

    window, profile = _login_flow_window(fresh_stores, tmp_path, "browser")
    qtbot.addWidget(window)
    window._login_then_launch(profile, "tskx")

    assert _FakeBrowserDialog.instances == 1
    assert _FakeWebDialog.instances == 0


def test_login_then_launch_forces_browser_when_helper_unavailable(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """No login helper (browser-only install) → a saved 'webview' preference
    is ignored and the browser flow is used."""
    monkeypatch.setattr(mw, "webview_available", lambda: False)
    _FakeWebDialog.instances = 0
    _FakeBrowserDialog.instances = 0
    monkeypatch.setattr(mw, "WebLoginDialog", _FakeWebDialog)
    monkeypatch.setattr(mw, "LoginDialog", _FakeBrowserDialog)

    window, profile = _login_flow_window(fresh_stores, tmp_path, "webview")
    qtbot.addWidget(window)
    window._login_then_launch(profile, "tskx")

    assert _FakeBrowserDialog.instances == 1
    assert _FakeWebDialog.instances == 0


def _auto_login_window(fresh_stores, tmp_path, *, method="webview", auto=True):
    profile_store, game_store = fresh_stores
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method=method, auto_login=auto))
    api = MagicMock(spec=DmmApiClient)
    return MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        settings_store=settings,
        cnf_path=FIXTURE_CNF,
    )


def test_auto_login_active_only_under_webview_and_setting(
    qtbot, fresh_stores, tmp_path
):
    w = _auto_login_window(fresh_stores, tmp_path, method="webview", auto=True)
    qtbot.addWidget(w)
    assert w._auto_login_active() is True


def test_auto_login_inactive_when_setting_off(qtbot, fresh_stores, tmp_path):
    w = _auto_login_window(fresh_stores, tmp_path, method="webview", auto=False)
    qtbot.addWidget(w)
    assert w._auto_login_active() is False


def test_auto_login_inactive_under_browser_method(qtbot, fresh_stores, tmp_path):
    w = _auto_login_window(fresh_stores, tmp_path, method="browser", auto=True)
    qtbot.addWidget(w)
    assert w._auto_login_active() is False


def test_auth_invalid_auto_schedules_relogin_and_closes(
    qtbot, fresh_stores, tmp_path
):
    from PyQt6.QtCore import QThread

    from shantytown.gui.progress_dialog import ProgressDialog

    w = _auto_login_window(fresh_stores, tmp_path)
    qtbot.addWidget(w)
    profile = w._profile_store.create("alice", token="live")
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    w._on_launch_auth_invalid(dialog, profile, "tskx", auto=True)

    assert w._auto_relogin_pending == "tskx"
    # No manual logout button offered in auto mode.
    assert dialog._logout_callback is None
    # The dialog is closed on the next tick.
    qtbot.waitUntil(lambda: not dialog.isVisible() or dialog.result() != 0, timeout=1000)


def test_auth_invalid_manual_enables_logout_button(qtbot, fresh_stores, tmp_path):
    from PyQt6.QtCore import QThread

    from shantytown.gui.progress_dialog import ProgressDialog

    w = _auto_login_window(fresh_stores, tmp_path, auto=False)
    qtbot.addWidget(w)
    profile = w._profile_store.create("alice", token="live")
    thread = QThread()
    dialog = ProgressDialog("t", thread)
    qtbot.addWidget(dialog)

    w._on_launch_auth_invalid(dialog, profile, "tskx", auto=False)

    assert w._auto_relogin_pending is None
    assert dialog._logout_callback is not None


def test_launch_finished_skips_failure_ui_during_pending_relogin(
    qtbot, fresh_stores, tmp_path
):
    w = _auto_login_window(fresh_stores, tmp_path)
    qtbot.addWidget(w)
    profile = w._profile_store.create("alice", token="live")
    cfg = GameConfig(product_id="tskx", exe_path=Path("g.exe"))
    w._silent_mode = True  # simulate a hidden silent launch
    w._auto_relogin_pending = "tskx"

    w._on_launch_finished(False, "boom", None, "tskx", profile, cfg)

    # Must NOT reveal the window — the retry will run after exec() returns.
    assert w._silent_mode is True
    assert w.isVisible() is False


def test_launch_success_clears_auto_relogin_attempts(qtbot, fresh_stores, tmp_path):
    w = _auto_login_window(fresh_stores, tmp_path)
    qtbot.addWidget(w)
    profile = w._profile_store.create("alice", token="live")
    cfg = GameConfig(product_id="tskx", exe_path=Path("g.exe"))
    w._auto_relogin_attempted.add("tskx")

    w._on_launch_finished(True, "", object(), "tskx", profile, cfg)

    assert "tskx" not in w._auto_relogin_attempted


def test_expired_token_triggers_auto_logout_and_relogin(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """End-to-end: an auth-invalid launch under auto-login silently logs
    out and re-runs the launch (which routes into the login flow) without
    the user touching the error dialog."""
    from dataclasses import replace

    from PyQt6.QtCore import QObject, pyqtSignal

    class FakeWorker(QObject):
        progress = pyqtSignal(str, int, int)
        finished = pyqtSignal(bool, str, object)
        auth_invalid = pyqtSignal()

        def __init__(self, **_kwargs: object) -> None:
            super().__init__()

        def run(self) -> None:
            # Expired token: signal the auth failure, then finish as failed.
            self.auth_invalid.emit()
            self.finished.emit(False, "auth", None)

    monkeypatch.setattr(mw, "LaunchWorker", FakeWorker)

    w = _auto_login_window(fresh_stores, tmp_path)
    qtbot.addWidget(w)
    profile = w._profile_store.create("alice", token="live", email="a@b.c")
    w._profile_store.update(replace(profile, password="pw"))
    w._game_store.upsert(GameConfig(product_id="tskx", exe_path=Path("g.exe")))
    w.refresh()

    relogin_calls: list[str] = []
    monkeypatch.setattr(
        w, "_login_then_launch", lambda prof, pid: relogin_calls.append(pid)
    )

    w._launch_game("tskx")

    # The token was cleared and the launch re-entered the login flow once.
    assert relogin_calls == ["tskx"]
    assert w._profile_store.get(profile.id).token is None
    # Bounded: the product is marked so a repeat auth failure won't loop.
    assert "tskx" in w._auto_relogin_attempted
    assert w._auto_relogin_pending is None


def test_webview_failure_text_maps_codes_and_flags_raw():
    assert (
        mw._webview_failure_text("helper_exited")
        == "로그인 도우미가 예기치 않게 종료되었습니다."
    )
    assert mw._webview_failure_text("form_not_found:no_fields").startswith(
        "로그인 페이지에서"
    )
    # Unmapped reasons (DMM's own server text) return None → shown verbatim.
    assert mw._webview_failure_text("メールアドレスが正しくありません。") is None


def test_profile_change_preserves_display_name(qtbot, fresh_stores):
    """Changing a game's profile must not wipe the display-name override."""
    profile_store, game_store = fresh_stores
    game_store.upsert(
        GameConfig(
            product_id="tskx", exe_path=Path("g.exe"), display_name="My Name"
        )
    )
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)

    window._on_profile_changed("tskx", "some-profile-id")

    cfg = game_store.get("tskx")
    assert cfg is not None
    assert cfg.display_name == "My Name"
    assert cfg.profile_id == "some-profile-id"


def test_save_exe_preserves_display_name(qtbot, fresh_stores, tmp_path):
    profile_store, game_store = fresh_stores
    game_store.upsert(GameConfig(product_id="tskx", display_name="Keep Me"))
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    installed = window._installed_by_id["tskx"]
    exe = tmp_path / "g.exe"
    exe.write_bytes(b"")

    window._save_exe(installed, exe)

    cfg = game_store.get("tskx")
    assert cfg is not None
    assert cfg.display_name == "Keep Me"
    assert cfg.exe_path == exe


def test_launch_finished_preserves_display_name(qtbot, fresh_stores):
    """Stamping last_played_at after a launch must not reset display_name."""
    profile_store, game_store = fresh_stores
    profile = profile_store.create("alice", token="tok")
    cfg = GameConfig(
        product_id="tskx",
        exe_path=Path("g.exe"),
        profile_id=profile.id,
        display_name="Launch Name",
    )
    game_store.upsert(cfg)
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)

    # popen is not a real subprocess.Popen → running-tracking is skipped.
    window._on_launch_finished(True, "", object(), "tskx", profile, cfg)

    stored = game_store.get("tskx")
    assert stored is not None
    assert stored.display_name == "Launch Name"
    assert stored.last_played_at is not None


def test_effective_login_method_webview_needs_no_debug(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """Webview is honoured whenever the helper is available — no --debug
    flag required (helper presence is the gate)."""
    monkeypatch.delenv("SHANTYTOWN_DEBUG", raising=False)
    profile_store, game_store = fresh_stores
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method="webview"))
    window = MainWindow(
        api=MagicMock(spec=DmmApiClient),
        profile_store=profile_store,
        game_store=game_store,
        settings_store=settings,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    assert window._effective_login_method() == "webview"


def test_effective_login_method_browser_when_webview_unavailable(
    qtbot, fresh_stores, tmp_path, monkeypatch
):
    """A browser-only build (no QtWebEngine) must never use webview."""
    monkeypatch.setenv("SHANTYTOWN_DEBUG", "1")
    monkeypatch.setattr(mw, "webview_available", lambda: False)
    profile_store, game_store = fresh_stores
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method="webview"))
    window = MainWindow(
        api=MagicMock(spec=DmmApiClient),
        profile_store=profile_store,
        game_store=game_store,
        settings_store=settings,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    assert window._effective_login_method() == "browser"


def test_card_profile_dropdown_omits_email(qtbot, fresh_stores):
    """The card's profile dropdown shows names only, not emails."""
    profile_store, game_store = fresh_stores
    profile_store.create("alice", email="a@b.c")
    api = MagicMock(spec=DmmApiClient)
    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        cnf_path=FIXTURE_CNF,
    )
    qtbot.addWidget(window)
    card = _all_cards(window)[0]
    labels = [
        card._profile_combo.itemText(i)
        for i in range(card._profile_combo.count())
    ]
    assert any("alice" in label for label in labels)
    assert not any("a@b.c" in label for label in labels)


def test_importing_main_window_does_not_load_qtwebengine():
    """QtWebEngine must stay unloaded until the first webview login.

    Run in a fresh interpreter so other tests that already imported the
    agent can't pollute sys.modules.
    """
    import subprocess
    import sys

    code = (
        "import sys; import shantytown.gui.main_window; "
        "sys.exit(1 if 'PyQt6.QtWebEngineCore' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "importing main_window pulled in QtWebEngine at startup:\n"
        + result.stderr
    )


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
