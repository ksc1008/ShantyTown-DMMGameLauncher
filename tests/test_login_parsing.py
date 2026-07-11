"""Tests for core.login_parsing — the DMM login structure parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shantytown.core.login_parsing import (
    extract_code,
    is_login_redirect,
    login_error_messages,
    parse_next_data,
)

_REPO_ROOT = Path(__file__).parent.parent


# --- extract_code ---


def test_extract_code_from_custom_scheme():
    assert extract_code("dmmgameplayer5://auth?code=ABC123&state=x") == "ABC123"


def test_extract_code_from_https_url():
    assert extract_code("https://example.com/cb?foo=1&code=xyz") == "xyz"


def test_extract_code_from_bare_fragment():
    assert extract_code("?code=only") == "only"


def test_extract_code_none_when_absent():
    assert extract_code("dmmgameplayer5://auth?state=x") is None


def test_extract_code_none_on_empty():
    assert extract_code("") is None


# --- is_login_redirect ---


def test_https_success_url_is_redirect():
    assert (
        is_login_redirect(
            "https://webdgp-gameplayer.games.dmm.com/login/success?code=abc"
        )
        is True
    )


def test_custom_scheme_is_redirect():
    assert is_login_redirect("dmmgameplayer5://x?code=abc") is True


def test_login_page_is_not_redirect():
    assert is_login_redirect("https://accounts.dmm.com/service/oauth") is False


def test_success_host_without_code_is_not_redirect():
    assert (
        is_login_redirect(
            "https://webdgp-gameplayer.games.dmm.com/login/success"
        )
        is False
    )


def test_unrelated_host_with_code_is_not_redirect():
    assert is_login_redirect("https://evil.example.com/login/success?code=x") is False


def test_empty_is_not_redirect():
    assert is_login_redirect("") is False


# --- login_error_messages ---


def _next_data(error: list[str]) -> str:
    return json.dumps({"props": {"pageProps": {"error": error}}})


def test_no_error_returns_empty():
    assert login_error_messages(_next_data([])) == []


def test_single_error_is_returned():
    msg = "メールアドレスまたはパスワードが正しくありません。"
    assert login_error_messages(_next_data([msg])) == [msg]


def test_multiple_errors_returned():
    assert login_error_messages(_next_data(["a", "b"])) == ["a", "b"]


def test_malformed_json_returns_empty():
    assert login_error_messages("{not json") == []


def test_missing_error_key_returns_empty():
    assert login_error_messages(json.dumps({"props": {"pageProps": {}}})) == []


def test_error_extracted_from_full_html():
    html = (
        "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + _next_data(["boom"])
        + "</script></body></html>"
    )
    assert login_error_messages(html) == ["boom"]


# --- parse_next_data ---


def test_parse_next_data_from_raw_json():
    data = parse_next_data('{"a": 1}')
    assert data == {"a": 1}


def test_parse_next_data_none_when_absent():
    assert parse_next_data("<html>no next data here</html>") is None


# --- against the real captured samples (if present in the repo root) ---


@pytest.mark.skipif(
    not (_REPO_ROOT / "error_response.html").is_file(),
    reason="reference error_response.html not present",
)
def test_real_error_response_reports_failure():
    html = (_REPO_ROOT / "error_response.html").read_text(encoding="utf-8")
    errors = login_error_messages(html)
    assert errors
    assert any("パスワード" in e for e in errors)


@pytest.mark.skipif(
    not (_REPO_ROOT / "sample_login.html").is_file(),
    reason="reference sample_login.html not present",
)
def test_real_login_page_has_no_error():
    html = (_REPO_ROOT / "sample_login.html").read_text(encoding="utf-8")
    assert login_error_messages(html) == []
