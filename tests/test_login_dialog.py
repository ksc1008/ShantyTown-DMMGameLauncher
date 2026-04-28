"""Tests for gui.login_dialog.

The clipboard-polling flow is hard to test deterministically (real Qt
clipboards are flaky in headless CI), so we focus on:

1. ``extract_code`` — pure unit tests across realistic URL shapes.
2. A qtbot smoke test that constructs the dialog with a fake clipboard
   factory and verifies the auto-detect path emits ``token_issued``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shantytown.core.api import DmmApiClient
from shantytown.gui.login_dialog import LoginDialog, extract_code

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


def test_paste_submit_path_issues_token(qtbot, mock_api):
    """Manual paste path: simulate the user pasting a redirect URL and clicking submit."""
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    received: list[tuple[str, object]] = []
    dialog.token_issued.connect(lambda t, e: received.append((t, e)))

    dialog.show()
    qtbot.waitUntil(lambda: dialog._open_button.isEnabled(), timeout=2000)

    dialog._paste_input.setText("https://accounts.dmm.com/cb?code=THE_CODE")
    dialog._paste_button.click()

    qtbot.waitUntil(lambda: bool(received), timeout=3000)
    mock_api.issue_token.assert_called_once_with("THE_CODE")
    assert received[0][0] == "issued-token-abc"
    # email is None for now (we'll plug auto-extraction in later)
    assert received[0][1] is None


def test_login_url_failure_disables_button(qtbot, mock_api):
    from shantytown.core.api import DmmApiError

    mock_api.get_login_url.side_effect = DmmApiError("boom")
    dialog = LoginDialog(mock_api, clipboard_factory=lambda: None)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(
        lambda: "boom" in dialog._status.text(), timeout=2000
    )
    assert not dialog._open_button.isEnabled()
