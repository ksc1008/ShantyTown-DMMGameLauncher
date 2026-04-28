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
