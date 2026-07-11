"""Tests for the _loginhelper session (protocol edges, no QtWebEngine).

The success path needs QtWebEngine + a real DMM login, so the session is
exercised with a fake agent factory: protocol parsing, request ids,
abort, and the keep-alive reuse across requests.
"""

from __future__ import annotations

import io
import json
import sys

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from shantytown import loginhelper
from shantytown.loginhelper import LoginSession


class _FakeAgent(QObject):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.started_with: tuple[str, str, str] | None = None
        self.aborted = False

    def start(self, url: str, email: str, password: str) -> None:
        self.started_with = (url, email, password)

    def abort(self) -> None:
        self.aborted = True


@pytest.fixture
def emitted(monkeypatch):
    """Collects every ``_emit`` payload (sys.stdout is pytest-managed)."""
    lines: list[dict] = []
    monkeypatch.setattr(loginhelper, "_emit", lines.append)
    return lines


def _session() -> tuple[LoginSession, list[_FakeAgent]]:
    agents: list[_FakeAgent] = []

    def factory() -> _FakeAgent:
        agent = _FakeAgent()
        agents.append(agent)
        return agent

    return LoginSession(agent_factory=factory), agents


def _request(req_id: int = 1) -> str:
    return json.dumps(
        {"id": req_id, "login_url": "https://x", "email": "e@x.y", "password": "pw"}
    )


# --- emit ---


def test_emit_writes_one_json_line(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    loginhelper._emit({"ok": True, "code": "abc"})
    assert json.loads(buf.getvalue().strip()) == {"ok": True, "code": "abc"}


def test_emit_survives_missing_stdout(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    loginhelper._emit({"ok": False})  # must not raise


class _LegacyCodePageStdout:
    """Stdout whose encoding can't represent non-ASCII (e.g. cp949)."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, s: str) -> None:
        s.encode("cp949")  # raises UnicodeEncodeError on Japanese
        self.text += s

    def flush(self) -> None:
        pass


def test_emit_japanese_survives_legacy_code_page(monkeypatch):
    """Regression: a Japanese error on a cp949 console must not be dropped.

    Silently losing it left the client waiting on an outcome forever
    ("영원히 로그인 중"). ``_emit`` falls back to ASCII-escaped JSON, which
    the client's ``json.loads`` restores to the original message.
    """
    out = _LegacyCodePageStdout()
    monkeypatch.setattr(sys, "stdout", out)
    msg = "メールアドレスまたはパスワードが正しくありません。"
    loginhelper._emit({"ok": False, "error": msg, "id": 1})
    assert out.text  # line was delivered, not swallowed
    assert json.loads(out.text)["error"] == msg


# --- protocol edges ---


def test_invalid_line_emits_error_and_session_survives(qapp, emitted):
    session, agents = _session()
    session.handle_line("not json\n")
    assert emitted == [{"ok": False, "error": "invalid_request"}]
    # The session keeps serving after a bad line.
    session.handle_line(_request(1))
    assert agents and agents[0].started_with == ("https://x", "e@x.y", "pw")


def test_non_object_request_emits_error(qapp, emitted):
    session, _ = _session()
    session.handle_line("[1, 2, 3]\n")
    assert emitted == [{"ok": False, "error": "invalid_request"}]


def test_blank_line_ignored(qapp, emitted):
    session, agents = _session()
    session.handle_line("   \n")
    assert emitted == []
    assert agents == []


# --- login lifecycle ---


def test_login_request_emits_ready_and_starts_agent(qapp, emitted):
    session, agents = _session()
    session.handle_line(_request(7))
    assert emitted == [{"status": "ready", "id": 7}]
    assert agents[0].started_with == ("https://x", "e@x.y", "pw")


def test_success_emits_ok_with_id_and_frees_the_slot(qapp, emitted):
    session, agents = _session()
    session.handle_line(_request(7))
    agents[0].succeeded.emit("CODE")
    assert emitted[-1] == {"ok": True, "code": "CODE", "id": 7}
    assert session._agent is None  # ready for the next request


def test_failure_emits_error_with_id(qapp, emitted):
    session, agents = _session()
    session.handle_line(_request(3))
    agents[0].failed.emit("timeout")
    assert emitted[-1] == {"ok": False, "error": "timeout", "id": 3}


def test_abort_cmd_aborts_silently_and_drops_late_outcome(qapp, emitted):
    session, agents = _session()
    session.handle_line(_request(1))
    session.handle_line('{"cmd": "abort"}')
    assert agents[0].aborted is True
    # No terminal line for the aborted request…
    assert emitted == [{"status": "ready", "id": 1}]
    # …and a late outcome from it is dropped.
    agents[0].succeeded.emit("late")
    assert emitted == [{"status": "ready", "id": 1}]


def test_new_request_replaces_inflight_login(qapp, emitted):
    session, agents = _session()
    session.handle_line(_request(1))
    session.handle_line(_request(2))
    assert agents[0].aborted is True
    # A late outcome from the replaced login is dropped…
    agents[0].failed.emit("stale")
    # …while the new one completes normally.
    agents[1].succeeded.emit("NEW")
    assert emitted[-1] == {"ok": True, "code": "NEW", "id": 2}
    assert not any(line.get("error") == "stale" for line in emitted)


def test_session_serves_multiple_requests(qapp, emitted):
    """The whole point of the long-lived helper: reuse across logins."""
    session, agents = _session()
    session.handle_line(_request(1))
    agents[0].failed.emit("bad creds")
    session.handle_line(_request(2))
    agents[1].succeeded.emit("CODE2")
    assert len(agents) == 2
    assert emitted[-1] == {"ok": True, "code": "CODE2", "id": 2}


# --- main entry ---


def test_main_no_stdin_returns_error(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert loginhelper.main([]) == 2
