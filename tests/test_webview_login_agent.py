"""Tests for the headless webview login agent.

The JS builders are pure and always tested. The agent's terminal wiring
(scheme capture → code, error JSON → failure) is tested by driving the
internal handlers directly, without any real network. Constructing the
agent needs QtWebEngine to initialise; if that fails in a headless CI
environment the agent tests skip rather than crash.
"""

from __future__ import annotations

import json

import pytest

from shantytown.gui import webview_login_agent as agent_mod
from shantytown.gui.webview_login_agent import (
    WebviewLoginAgent,
    fill_and_submit_js,
    read_next_data_js,
    ready_js,
)

# --- JS builders (pure) ---


def test_fill_js_embeds_selectors_and_credentials():
    js = fill_and_submit_js("me@example.com", "pw'\"<script>")
    assert "#login_id" in js
    assert "#password" in js
    # Credentials are JSON-encoded so quotes/brackets can't break out.
    assert json.dumps("me@example.com") in js
    assert json.dumps("pw'\"<script>") in js
    assert ".click()" in js


def test_ready_js_checks_form_and_recaptcha():
    js = ready_js()
    assert "#login_id" in js
    assert "grecaptcha" in js


def test_read_next_data_js_targets_next_data():
    assert "__NEXT_DATA__" in read_next_data_js()


# --- agent terminal wiring ---


@pytest.fixture
def agent(qtbot):
    try:
        a = WebviewLoginAgent()
    except Exception as e:  # pragma: no cover - env-dependent
        pytest.skip(f"QtWebEngine unavailable: {e}")
    yield a


def test_https_redirect_capture_emits_code(agent, qtbot):
    url = "https://webdgp-gameplayer.games.dmm.com/login/success?code=Tok42"
    with qtbot.waitSignal(agent.succeeded, timeout=1000) as blocker:
        agent._on_redirect_captured(url)
    assert blocker.args == ["Tok42"]


def test_scheme_capture_emits_code(agent, qtbot):
    with qtbot.waitSignal(agent.succeeded, timeout=1000) as blocker:
        agent._on_redirect_captured("dmmgameplayer5://auth?code=Tok42&state=x")
    assert blocker.args == ["Tok42"]


def test_capture_redirect_defers_processing_then_succeeds(agent, qtbot):
    # _capture_redirect runs inside the nav callback: it must only stash +
    # schedule, so success arrives on a later event-loop turn.
    url = "https://webdgp-gameplayer.games.dmm.com/login/success?code=Deferred1"
    with qtbot.waitSignal(agent.succeeded, timeout=1000) as blocker:
        agent._capture_redirect(url)
    assert blocker.args == ["Deferred1"]


def test_redirect_without_code_fails(agent, qtbot):
    with qtbot.waitSignal(agent.failed, timeout=1000):
        agent._on_redirect_captured("dmmgameplayer5://auth?state=x")


def test_abort_is_silent_and_marks_done(agent, qtbot):
    with qtbot.assertNotEmitted(agent.succeeded):
        with qtbot.assertNotEmitted(agent.failed):
            agent.abort()
    assert agent._done is True
    # A later redirect after abort must be ignored.
    with qtbot.assertNotEmitted(agent.succeeded):
        agent._on_redirect_captured("dmmgameplayer5://auth?code=late")


def test_next_data_error_emits_failure(agent, qtbot):
    payload = json.dumps(
        {"props": {"pageProps": {"error": ["メールアドレスまたはパスワードが正しくありません。"]}}}
    )
    agent._submitted = True
    with qtbot.waitSignal(agent.failed, timeout=1000) as blocker:
        agent._on_next_data(payload)
    assert "パスワード" in blocker.args[0]


def test_next_data_without_error_does_not_emit(agent, qtbot):
    payload = json.dumps({"props": {"pageProps": {"error": []}}})
    agent._submitted = True
    # No error → the agent keeps waiting; neither signal should fire.
    with qtbot.assertNotEmitted(agent.failed):
        agent._on_next_data(payload)
    assert agent._done is False


def test_terminal_state_ignores_later_events(agent, qtbot):
    with qtbot.waitSignal(agent.succeeded, timeout=1000):
        agent._on_redirect_captured("dmmgameplayer5://auth?code=first")
    # After finishing, a second capture must be ignored (no double emit).
    with qtbot.assertNotEmitted(agent.succeeded):
        agent._on_redirect_captured("dmmgameplayer5://auth?code=second")


def test_module_exposes_selectors():
    # Selectors are centralised for prompt-fixability (requirement 3).
    assert agent_mod._LOGIN_ID_SELECTOR == "#login_id"
    assert agent_mod._PASSWORD_SELECTOR == "#password"
