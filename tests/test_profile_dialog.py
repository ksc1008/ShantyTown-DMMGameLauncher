"""Tests for profile_dialog pure helpers + dialog behavior.

The HTML rendering is hard to assert visually, so we cover the helpers
(``needs_relogin``, ``format_profile_html``) directly and reach into the
dialog only for the logout flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from shantytown.core.api import DmmApiClient
from shantytown.gui.profile_dialog import (
    ProfileDialog,
    format_profile_html,
    needs_relogin,
)
from shantytown.store.profiles import Profile, ProfileStore
from shantytown.store.settings import SettingsStore


def _make(token: str | None, name: str = "alice", email: str | None = None) -> Profile:
    return Profile(
        id="pid",
        name=name,
        token=token,
        created_at=datetime.now(UTC),
        last_used_at=None,
        email=email,
    )


# --- needs_relogin ---


def test_needs_relogin_when_no_token():
    assert needs_relogin(_make(None)) is True


def test_needs_relogin_when_empty_token():
    assert needs_relogin(_make("")) is True


def test_does_not_need_relogin_when_token_present():
    assert needs_relogin(_make("abc")) is False


# --- format_profile_html ---


def test_format_includes_default_marker_when_default():
    html = format_profile_html(_make("tok", name="primary"), is_default=True)
    assert "(기본)" in html
    assert "primary" in html


def test_format_omits_default_marker_when_not_default():
    html = format_profile_html(_make("tok", name="alt"), is_default=False)
    assert "(기본)" not in html
    assert "alt" in html


def test_format_shows_orange_relogin_badge_when_no_token():
    html = format_profile_html(_make(None), is_default=False)
    assert "재로그인 필요" in html
    # orange/amber color code is present
    assert "#f59e0b" in html


def test_format_omits_relogin_badge_when_token_present():
    html = format_profile_html(_make("tok"), is_default=False)
    assert "재로그인 필요" not in html


def test_format_includes_email_when_present():
    html = format_profile_html(
        _make("tok", name="alice", email="a@b.c"), is_default=False
    )
    assert "a@b.c" in html


def test_format_email_is_blue():
    html = format_profile_html(
        _make("tok", name="alice", email="a@b.c"), is_default=False
    )
    assert "a@b.c" in html
    assert "#4a90d9" in html  # blue-toned email


def test_format_includes_last_used_section():
    html = format_profile_html(_make("tok"), is_default=False)
    assert "마지막 사용" in html


# --- logout flow ---


@pytest.fixture
def store_with_profile(tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    profile = store.create("alice", token="active-token", email="a@b.c")
    return store, profile


def test_logout_clears_token(qtbot, store_with_profile, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    store, profile = store_with_profile
    api = MagicMock(spec=DmmApiClient)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **kw: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)

    dialog = ProfileDialog(store, api)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)
    dialog._logout()

    refreshed = store.get(profile.id)
    assert refreshed is not None
    assert refreshed.token is None
    # Email and identity preserved
    assert refreshed.email == "a@b.c"
    assert refreshed.name == "alice"


# --- login-method toggle ---


def test_login_method_switch_hidden_without_settings_store(qtbot, tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api)
    qtbot.addWidget(dialog)
    assert dialog._login_method_row.isHidden()


def test_login_method_switch_visible_with_helper_and_settings(qtbot, tmp_path):
    # Helper is available in dev → toggle shown (no --debug needed).
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._login_method_row.isVisible()


def test_login_method_switch_hidden_when_webview_unavailable(
    qtbot, tmp_path, monkeypatch
):
    """Browser-only build: no QtWebEngine → toggle hidden even in debug."""
    import shantytown.gui.profile_dialog as pd

    monkeypatch.setenv("SHANTYTOWN_DEBUG", "1")
    monkeypatch.setattr(pd, "webview_available", lambda: False)
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    assert dialog._login_method_row.isHidden()


def test_login_method_switch_reflects_persisted_method(qtbot, tmp_path, monkeypatch):
    from shantytown.store.settings import Settings

    monkeypatch.setenv("SHANTYTOWN_DEBUG", "1")
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method="webview"))
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    assert dialog._login_method_switch.isChecked() is True


def test_login_method_switch_flips_and_persists(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("SHANTYTOWN_DEBUG", "1")
    store = ProfileStore(tmp_path / "profiles.json")
    settings_path = tmp_path / "settings.json"
    settings = SettingsStore(settings_path)
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)

    # Default is browser (switch off).
    assert settings.get().login_method == "browser"
    assert dialog._login_method_switch.isChecked() is False

    dialog._login_method_switch.setChecked(True)  # emits toggled(True)
    assert settings.get().login_method == "webview"
    assert SettingsStore(settings_path).get().login_method == "webview"

    dialog._login_method_switch.setChecked(False)
    assert settings.get().login_method == "browser"


def test_login_method_switch_preserves_theme(qtbot, tmp_path, monkeypatch):
    """Flipping the login method must not clobber other settings fields."""
    from shantytown.store.settings import Settings

    monkeypatch.setenv("SHANTYTOWN_DEBUG", "1")
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(theme="dark", tutorial_completed=True))
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)

    dialog._login_method_switch.setChecked(True)
    loaded = settings.get()
    assert loaded.login_method == "webview"
    assert loaded.theme == "dark"
    assert loaded.tutorial_completed is True


# --- auto-login sub-toggle (shown only under webview login) ---


def test_auto_login_hidden_when_webview_off(qtbot, tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")  # browser default
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._auto_login_widget.isVisible() is False


def test_auto_login_shown_when_webview_on(qtbot, tmp_path):
    from shantytown.store.settings import Settings

    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.update(Settings(login_method="webview"))
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._auto_login_widget.isVisible() is True


def test_toggling_webview_reveals_and_hides_auto_login(qtbot, tmp_path):
    store = ProfileStore(tmp_path / "profiles.json")
    settings = SettingsStore(tmp_path / "settings.json")
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog._auto_login_widget.isVisible() is False
    dialog._login_method_switch.setChecked(True)  # webview on
    assert dialog._auto_login_widget.isVisible() is True
    dialog._login_method_switch.setChecked(False)  # webview off
    assert dialog._auto_login_widget.isVisible() is False


def test_auto_login_switch_flips_and_persists(qtbot, tmp_path):
    from shantytown.store.settings import Settings

    store = ProfileStore(tmp_path / "profiles.json")
    settings_path = tmp_path / "settings.json"
    settings = SettingsStore(settings_path)
    settings.update(Settings(login_method="webview"))
    api = MagicMock(spec=DmmApiClient)
    dialog = ProfileDialog(store, api, settings_store=settings)
    qtbot.addWidget(dialog)

    assert dialog._auto_login_switch.isChecked() is False
    dialog._auto_login_switch.setChecked(True)
    assert settings.get().auto_login is True
    assert SettingsStore(settings_path).get().auto_login is True
    # Other fields preserved.
    assert settings.get().login_method == "webview"


def test_logout_noop_when_already_logged_out(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    store = ProfileStore(tmp_path / "profiles.json")
    profile = store.create("alice")  # token=None by default
    api = MagicMock(spec=DmmApiClient)

    info_calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **kw: info_calls.append(a),
    )
    # If question() is reached we have a bug — answer Yes so we'd notice
    # by seeing the token cleared (it already was None, so test stays valid).
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **kw: QMessageBox.StandardButton.Yes,
    )

    dialog = ProfileDialog(store, api)
    qtbot.addWidget(dialog)
    dialog._list.setCurrentRow(0)
    dialog._logout()

    # Should have shown an information message ("이미 로그아웃 상태")
    assert info_calls
    assert store.get(profile.id).token is None
