"""Tests for the webview login IPC client (no real process spawned)."""

from __future__ import annotations

import sys

from shantytown.gui import webview_login_client as wlc
from shantytown.gui.webview_login_client import WebviewLoginClient, helper_command

# --- helper_command resolution ---


def test_helper_command_dev_runs_module(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = helper_command()
    assert cmd is not None
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["-m", "shantytown.loginhelper"]


def test_helper_command_frozen_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "shantytown.exe"))
    assert helper_command() is None


def test_helper_command_frozen_present(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "shantytown.exe"))
    name = "__loginhelper.exe" if sys.platform == "win32" else "__loginhelper"
    helper = tmp_path / name
    helper.write_text("")
    assert helper_command() == [str(helper)]


# --- client behavior (parse logic; no process) ---


def _in_flight(client: WebviewLoginClient, req_id: int = 1) -> None:
    """Put the client in the state of an outstanding request ``req_id``."""
    client._done = False
    client._req_id = req_id


def test_start_without_helper_fails_with_code(qtbot, monkeypatch):
    monkeypatch.setattr(wlc, "helper_command", lambda: None)
    client = WebviewLoginClient()
    with qtbot.waitSignal(client.failed, timeout=1000) as blocker:
        client.start("https://x", "e@x.y", "pw")
    assert blocker.args == ["helper_missing"]


def test_ready_line_emits_engine_ready(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.waitSignal(client.engineReady, timeout=500):
        client._handle_line('{"status": "ready", "id": 1}')
    assert client._done is False


def test_ok_line_emits_success(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.waitSignal(client.succeeded, timeout=500) as blocker:
        client._handle_line('{"ok": true, "code": "XYZ", "id": 1}')
    assert blocker.args == ["XYZ"]


def test_line_without_id_still_accepted(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.waitSignal(client.succeeded, timeout=500) as blocker:
        client._handle_line('{"ok": true, "code": "XYZ"}')
    assert blocker.args == ["XYZ"]


def test_stale_id_line_ignored(qtbot):
    """A late response from an aborted/replaced request must be dropped."""
    client = WebviewLoginClient()
    _in_flight(client, req_id=2)
    with qtbot.assertNotEmitted(client.succeeded):
        with qtbot.assertNotEmitted(client.failed):
            client._handle_line('{"ok": true, "code": "old", "id": 1}')
    assert client._done is False  # request 2 is still outstanding


def test_ok_without_code_fails(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.waitSignal(client.failed, timeout=500):
        client._handle_line('{"ok": true, "code": "", "id": 1}')


def test_error_line_emits_failure(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.waitSignal(client.failed, timeout=500) as blocker:
        client._handle_line('{"ok": false, "error": "bad creds", "id": 1}')
    assert blocker.args == ["bad creds"]


def test_non_json_line_ignored(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.assertNotEmitted(client.succeeded):
        with qtbot.assertNotEmitted(client.failed):
            client._handle_line("PyInstaller: loading bootloader...")
    assert client._done is False


def test_abort_is_silent_and_marks_done(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.assertNotEmitted(client.failed):
        client.abort()
    assert client._done is True
    # Post-abort lines are ignored.
    with qtbot.assertNotEmitted(client.succeeded):
        client._handle_line('{"ok": true, "code": "late", "id": 1}')


def test_abort_without_request_is_noop(qtbot):
    client = WebviewLoginClient()
    with qtbot.assertNotEmitted(client.failed):
        client.abort()  # nothing in flight — must not raise or emit


def test_shutdown_is_silent(qtbot):
    client = WebviewLoginClient()
    _in_flight(client)
    with qtbot.assertNotEmitted(client.failed):
        client.shutdown()
    assert client._done is True
