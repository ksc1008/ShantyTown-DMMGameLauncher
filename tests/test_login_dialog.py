"""Tests for gui.login_dialog.

The clipboard-polling flow is hard to test deterministically (real Qt
clipboards are flaky in headless CI), so we focus on:

1. ``extract_code`` — pure unit tests across realistic URL shapes.
2. Dialog pieces exercised **synchronously**. The paste→issue path is
   NOT driven end-to-end through its real ``QThread``: a live worker
   thread racing dialog teardown can deadlock the Qt C++ layer and
   freeze pytest forever (observed on Windows/offscreen). Instead the
   hand-off, the worker, and the success slot are each tested directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shantytown.core.api import DmmApiClient, DmmApiError
from shantytown.gui.login_dialog import (
    LoginDialog,
    _IssueTokenWorker,
    extract_code,
)

# --- extract_code ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://accounts.dmm.com/cb?code=ABC123", "ABC123"),
        ("https://accounts.dmm.com/cb?state=x&code=ABC123&y=1", "ABC123"),
        ("dmmgameplayer5://callback?code=XYZ", "XYZ"),
        ("?code=onlyparam", "onlyparam"),
        ("", None),
        ("https://accounts.dmm.com/cb?nocode=here", None),
        ("just some random text", None),
        ("  https://x.com/cb?code=trim_me  ", "trim_me"),
    ],
)
def test_extract_code(text, expected):
    assert extract_code(text) == expected


# --- dialog integration ---


@pytest.fixture
def mock_api():
    api = MagicMock(spec=DmmApiClient)
    api.get_login_url.return_value = "https://accounts.dmm.com/login?challenge=x"
    api.issue_token.return_value = "issued-token-abc"
    return api


def test_login_url_load_and_button_enabled(qtbot, mock_api):
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._open_button.isEnabled(), timeout=2000)
    mock_api.get_login_url.assert_called_once()


def test_paste_submit_hands_code_to_issue_flow(qtbot, mock_api, monkeypatch):
    """Manual paste path: submit extracts the code and starts issuance.

    ``_handle_code`` itself is stubbed — it spins a real QThread, which
    must not run in tests (see module docstring).
    """
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    codes: list[str] = []
    monkeypatch.setattr(dialog, "_handle_code", codes.append)

    dialog._paste_input.setText("https://accounts.dmm.com/cb?code=THE_CODE")
    dialog._paste_button.click()

    assert codes == ["THE_CODE"]


def test_issue_token_worker_success(qtbot, mock_api):
    worker = _IssueTokenWorker(mock_api, "THE_CODE")
    with qtbot.waitSignal(worker.succeeded, timeout=1000) as blocker:
        worker.run()  # synchronously — no QThread
    assert blocker.args == ["issued-token-abc"]
    mock_api.issue_token.assert_called_once_with("THE_CODE")


def test_issue_token_worker_failure(qtbot, mock_api):
    mock_api.issue_token.side_effect = DmmApiError("boom")
    worker = _IssueTokenWorker(mock_api, "THE_CODE")
    with qtbot.waitSignal(worker.failed, timeout=1000) as blocker:
        worker.run()
    assert "boom" in blocker.args[0]


def test_issue_success_emits_token_and_accepts(qtbot, mock_api):
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    received: list[tuple[str, object]] = []
    dialog.token_issued.connect(lambda t, e: received.append((t, e)))

    dialog._on_issue_success("issued-token-abc")

    assert received == [("issued-token-abc", None)]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_login_url_failure_disables_button(qtbot, mock_api):
    mock_api.get_login_url.side_effect = DmmApiError("boom")
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(
        lambda: "boom" in dialog._status.text(), timeout=2000
    )
    assert not dialog._open_button.isEnabled()
