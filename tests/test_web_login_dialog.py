"""Tests for the webview credential login form."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLineEdit

from shantytown.gui.web_login_dialog import WebLoginDialog
from shantytown.store.profiles import Profile, ProfileStore

_MASKED = QLineEdit.EchoMode.Password
_SHOWN = QLineEdit.EchoMode.Normal


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "profiles.json")


def _profile(store, *, email=None, password=None) -> Profile:
    p = store.create("alice", email=email)
    if password is not None:
        updated = Profile(
            id=p.id,
            name=p.name,
            token=p.token,
            created_at=p.created_at,
            last_used_at=p.last_used_at,
            email=p.email,
            password=password,
        )
        store.update(updated)
        return updated
    return p


# --- initial mode ---


def test_no_credentials_starts_in_edit_mode(qtbot, store):
    p = _profile(store)
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    assert dlg._edit_mode is True
    assert dlg._email_input.isReadOnly() is False
    assert dlg._password_input.isReadOnly() is False
    # Primary button is the green "완료" and disabled (fields empty).
    assert dlg._primary_btn.text() == "완료"
    assert dlg._primary_btn.isEnabled() is False
    # No saved state to revert to → the edit toggle is hidden.
    assert dlg._edit_toggle.isHidden() is True


def test_email_only_starts_in_edit_mode(qtbot, store):
    p = _profile(store, email="a@b.c")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    assert dlg._edit_mode is True
    assert dlg._edit_toggle.isHidden() is True


def test_both_credentials_start_in_view_mode(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    assert dlg._edit_mode is False
    assert dlg._email_input.isReadOnly() is True
    assert dlg._password_input.isReadOnly() is True
    assert dlg._primary_btn.text() == "로그인"
    assert dlg._primary_btn.isEnabled() is True
    assert dlg._email_input.text() == "a@b.c"
    assert dlg._password_input.text() == "pw"


def test_edit_toggle_visible_when_credentials_present(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._edit_toggle.isVisible() is True


# --- password reveal ---


def test_password_reveal_toggles_echo_in_view_mode(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    # View mode: reveal available, starts masked.
    assert dlg._reveal_action.isVisible() is True
    assert dlg._password_input.echoMode() == _MASKED
    dlg._toggle_password_reveal()
    assert dlg._password_input.echoMode() == _SHOWN
    dlg._toggle_password_reveal()
    assert dlg._password_input.echoMode() == _MASKED


def test_password_forced_masked_and_reveal_hidden_in_edit(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._toggle_password_reveal()  # reveal while in view mode
    assert dlg._password_input.echoMode() == _SHOWN
    dlg._on_edit_toggle_clicked()  # enter edit mode
    # Editing forces the mask back on and hides the reveal control.
    assert dlg._password_input.echoMode() == _MASKED
    assert dlg._reveal_action.isVisible() is False


def test_no_credentials_starts_masked_with_reveal_hidden(qtbot, store):
    p = _profile(store)  # no creds → edit mode
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    assert dlg._password_input.echoMode() == _MASKED
    assert dlg._reveal_action.isVisible() is False


# --- entering / cancelling edit ---


def test_toggle_into_edit_mode_switches_primary_to_done(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._on_edit_toggle_clicked()
    assert dlg._edit_mode is True
    assert dlg._email_input.isReadOnly() is False
    assert dlg._primary_btn.text() == "완료"
    # Fields are still filled, so done is enabled.
    assert dlg._primary_btn.isEnabled() is True


def test_toggle_is_green_edit_in_view_and_neutral_cancel_in_edit(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    # View mode: green "수정".
    assert dlg._edit_toggle.text() == "수정"
    assert "#10b981" in dlg._edit_toggle.styleSheet()
    dlg._on_edit_toggle_clicked()
    # Edit mode: default-colored "취소".
    assert dlg._edit_toggle.text() == "취소"
    assert "#10b981" not in dlg._edit_toggle.styleSheet()
    dlg._on_edit_toggle_clicked()
    # Back in view mode the green "수정" returns.
    assert dlg._edit_toggle.text() == "수정"
    assert "#10b981" in dlg._edit_toggle.styleSheet()


def test_cancel_edit_reverts_changes(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._on_edit_toggle_clicked()  # enter edit
    dlg._email_input.setText("changed@x.y")
    dlg._password_input.setText("newpw")
    dlg._on_edit_toggle_clicked()  # toggle again → cancel edit

    assert dlg._edit_mode is False
    # Fields reverted to the saved values; nothing persisted.
    assert dlg._email_input.text() == "a@b.c"
    assert dlg._password_input.text() == "pw"
    assert store.get(p.id).email == "a@b.c"
    assert store.get(p.id).password == "pw"


# --- completing edit ---


def test_complete_edit_saves_and_returns_to_view(qtbot, store):
    p = _profile(store)
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._email_input.setText("new@b.c")
    dlg._password_input.setText("secret")
    dlg._on_primary_clicked()  # "완료" commits the edit

    assert dlg._edit_mode is False
    assert dlg._primary_btn.text() == "로그인"
    assert dlg._primary_btn.isEnabled() is True
    loaded = store.get(p.id)
    assert loaded.email == "new@b.c"
    assert loaded.password == "secret"


def test_edit_toggle_appears_after_first_save(qtbot, store):
    """Entering first-time credentials makes the edit toggle available."""
    p = _profile(store)
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._edit_toggle.isVisible() is False
    dlg._email_input.setText("new@b.c")
    dlg._password_input.setText("secret")
    dlg._on_primary_clicked()
    assert dlg._edit_toggle.isVisible() is True


def test_complete_edit_with_empty_field_warns_and_stays(qtbot, store, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    warned: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **kw: warned.append(a)
    )
    p = _profile(store)
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._email_input.setText("new@b.c")
    dlg._password_input.setText("")  # missing password
    dlg._on_primary_clicked()

    assert warned  # warned the user
    assert dlg._edit_mode is True  # stayed in edit mode
    assert store.get(p.id).password is None  # nothing saved


# --- login ---


def test_login_emits_signal_and_enters_progress(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.login_requested, timeout=1000) as blocker:
        dlg._on_primary_clicked()  # in view mode this logs in
    assert blocker.args == ["a@b.c", "pw"]
    # Dialog stays open in a progress state (owner drives the outcome).
    assert dlg.isVisible() is False  # never shown in the test
    assert dlg.result() != dlg.DialogCode.Accepted
    assert dlg._progress_bar.isVisibleTo(dlg) is True
    assert dlg._primary_btn.isEnabled() is False
    # Cancel stays enabled so an in-flight login can be aborted.
    assert dlg._cancel_btn.isEnabled() is True


def test_enter_progress_shows_engine_loading_then_can_switch(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.enter_progress()
    # First phase is the webview-engine load.
    assert dlg._status_label.text() == "웹뷰 로드중…"
    # Owner flips to the sign-in phase once the engine is ready.
    dlg.set_progress_status("로그인 중… 잠시만 기다려주세요.")
    assert dlg._status_label.text() == "로그인 중… 잠시만 기다려주세요."


def test_show_error_leaves_progress_and_allows_retry(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._on_primary_clicked()  # enter progress
    dlg.show_error("boom")
    assert dlg._progress_bar.isVisibleTo(dlg) is False
    # Failure headline + the reason both show.
    assert "로그인 실패" in dlg._status_label.text()
    assert "boom" in dlg._status_label.text()
    # No raw site message → the [Message] field stays hidden.
    assert dlg._site_message_field.isVisibleTo(dlg) is False
    # Retry is possible again: cancel + primary + edit toggle re-enabled.
    assert dlg._cancel_btn.isEnabled() is True
    assert dlg._primary_btn.isEnabled() is True
    assert dlg._edit_toggle.isEnabled() is True


def test_show_error_with_site_message_shows_copyable_field(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg._on_primary_clicked()  # enter progress
    msg = "メールアドレスまたはパスワードが正しくありません。"
    dlg.show_error(site_message=msg)

    # Headline shows; the raw message lives in a read-only, selectable field
    # with the "[Message]" prefix inline (no separate label).
    assert "로그인 실패" in dlg._status_label.text()
    assert dlg._site_message_field.isVisibleTo(dlg) is True
    assert dlg._site_message_field.toPlainText() == f"[Message] {msg}"
    assert dlg._site_message_field.isReadOnly() is True
    # Copyable/draggable: selecting all yields the exact text.
    dlg._site_message_field.selectAll()
    assert dlg._site_message_field.textCursor().selectedText() == f"[Message] {msg}"


def test_long_site_message_expands_then_caps_with_scrollbar(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    # Short message → compact field.
    dlg.show_error(site_message="짧음")
    qtbot.waitUntil(lambda: dlg._site_message_field.height() > 0, timeout=1000)
    short_h = dlg._site_message_field.height()

    # Long message → field expands vertically…
    long_msg = "매우 긴 오류 메시지입니다. " * 40
    dlg.show_error(site_message=long_msg)
    qtbot.waitUntil(
        lambda: dlg._site_message_field.height() > short_h, timeout=1000
    )
    tall_h = dlg._site_message_field.height()
    # …but is capped at the max height (past it the field scrolls).
    assert tall_h <= dlg._SITE_MESSAGE_MAX_H
    # Content overflows the capped field → its vertical scrollbar is active.
    sb = dlg._site_message_field.verticalScrollBar()
    assert sb.maximum() > 0


def test_site_message_cleared_on_retry(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.show_error(site_message="なにか")
    assert dlg._site_message_field.isVisibleTo(dlg) is True
    dlg.enter_progress()  # retry → the stale site message must disappear
    assert dlg._site_message_field.isVisibleTo(dlg) is False


def test_auto_login_submits_when_credentials_saved(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store, auto_login=True)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.login_requested, timeout=1000) as blocker:
        pass  # the deferred auto-submit fires on the event loop
    assert blocker.args == ["a@b.c", "pw"]
    # It entered the progress state just like a manual click.
    assert dlg._progress_bar.isVisibleTo(dlg) is True


def test_auto_login_does_not_submit_without_saved_credentials(qtbot, store):
    p = _profile(store)  # no creds → edit mode, nothing to auto-submit
    dlg = WebLoginDialog(p, store, auto_login=True)
    qtbot.addWidget(dlg)
    with qtbot.assertNotEmitted(dlg.login_requested):
        qtbot.wait(200)
    assert dlg._edit_mode is True


def test_no_auto_login_waits_for_click(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store, auto_login=False)
    qtbot.addWidget(dlg)
    with qtbot.assertNotEmitted(dlg.login_requested):
        qtbot.wait(200)


def test_primary_disabled_when_fields_blank_in_edit(qtbot, store):
    p = _profile(store, email="a@b.c", password="pw")
    dlg = WebLoginDialog(p, store)
    qtbot.addWidget(dlg)
    dlg._on_edit_toggle_clicked()  # edit mode
    dlg._email_input.setText("")
    dlg._password_input.setText("")
    assert dlg._primary_btn.isEnabled() is False
