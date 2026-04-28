"""Tests for core.api.DmmApiClient using pytest-httpx."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from pytest_httpx import HTTPXMock

from shantytown.core.api import (
    AuthInvalidError,
    DmmApiClient,
    DmmApiError,
    GameNotLinkedError,
)
from shantytown.core.models import HardwareIds

BASE = "https://apidgp-gameplayer.games.dmm.com"


@pytest.fixture
def client() -> Iterator[DmmApiClient]:
    c = DmmApiClient(sleep=lambda _: None)
    try:
        yield c
    finally:
        c.close()


def test_get_login_url_returns_data_url(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/login/url",
        json={"data": {"url": "https://accounts.dmm.com/login?challenge=xyz"}},
    )
    assert client.get_login_url() == "https://accounts.dmm.com/login?challenge=xyz"


def test_region_lock_bypass_cookie_on_every_request(
    client, httpx_mock: HTTPXMock
):
    """Regression: the ``ckcy_remedied_check`` cookie has to ride on
    every endpoint, not just launch — otherwise the gateway region-locks
    auth calls before any of our flow can run from non-JP IPs.

    Verify against ``get_login_url`` (an auth endpoint that previously
    had no cookie) and ``check_token``.
    """
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/login/url",
        json={"data": {"url": "u"}},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/accesstoken/check",
        json={"data": {"result": True}},
    )

    client.get_login_url()
    client.check_token("tok")

    for req in httpx_mock.get_requests():
        cookie = req.headers.get("cookie", "")
        assert "ckcy_remedied_check=ec_mrnhbtk" in cookie, (
            f"region-bypass cookie missing on {req.url}"
        )
        assert "age_check_done=1" in cookie


def test_get_login_url_sends_prompt_choose(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/login/url",
        json={"data": {"url": "x"}},
    )
    client.get_login_url()
    req = httpx_mock.get_request()
    assert req is not None
    assert json.loads(req.content) == {"prompt": "choose"}


def test_issue_token_returns_access_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/accesstoken/issue",
        json={"data": {"access_token": "tok-abc"}},
    )
    assert client.issue_token("code-xyz") == "tok-abc"
    req = httpx_mock.get_request()
    assert req is not None
    assert json.loads(req.content) == {"code": "code-xyz"}


def test_check_token_true(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/accesstoken/check",
        json={"data": {"result": True}},
    )
    assert client.check_token("tok") is True


def test_check_token_false_does_not_raise(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/accesstoken/check",
        json={"data": {"result": False}},
    )
    assert client.check_token("tok") is False


def test_launch_game_payload_and_headers(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/r2/launch/cl",
        json={
            "data": {
                "sign": "cdn-sign-value",
                "file_list_url": "/v5/r2/launch/filelist?token=...",
                "execute_args": "--something",
            }
        },
    )
    hwid = HardwareIds(
        mac_address="aa:bb:cc:dd:ee:ff",
        hdd_serial="hdd-hash",
        motherboard="mb-hash",
    )
    resp = client.launch_game("the-token", "tskx", "ACL", hwid)
    assert resp.cdn_sign == "cdn-sign-value"
    assert resp.file_list_url == "/v5/r2/launch/filelist?token=..."
    assert resp.execute_args == "--something"

    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers.get("actauth") == "the-token"
    assert "age_check_done=1" in req.headers.get("cookie", "")
    assert "ckcy_remedied_check=ec_mrnhbtk" in req.headers.get("cookie", "")
    body = json.loads(req.content)
    assert body == {
        "product_id": "tskx",
        "game_type": "ACL",
        "game_os": "win",
        "launch_type": "SCHEME",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "hdd_serial": "hdd-hash",
        "motherboard": "mb-hash",
        "user_os": "win",
    }


def test_get_filelist_lowercases_hash_and_returns_domain(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/filelist",
        json={
            "data": {
                "domain": "https://cdn.example.com",
                "file_list": [
                    {
                        "local_path": "bin/game.exe",
                        "path": "/cdn/bin/game.exe",
                        "hash": "ABCDEF1234567890ABCDEF1234567890",
                        "size": 12345,
                    }
                ],
            }
        },
    )
    entries, domain = client.get_filelist("tok", "/filelist")
    assert domain == "https://cdn.example.com"
    assert len(entries) == 1
    assert entries[0].local_path == "bin/game.exe"
    assert entries[0].remote_path == "/cdn/bin/game.exe"
    assert entries[0].hash == "abcdef1234567890abcdef1234567890"
    assert entries[0].size == 12345


def test_get_filelist_strips_leading_slash_from_local_path(
    client, httpx_mock: HTTPXMock
):
    """Regression: API returns ``/foo.dll`` and ``Path("C:/x") / "/foo.dll"``
    on Windows resets to ``C:/foo.dll`` — strip the leading separator at
    the API boundary so downstream verify/download get a clean relative path."""
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/filelist",
        json={
            "data": {
                "domain": "https://cdn.example.com",
                "file_list": [
                    {
                        "local_path": "/GameAssembly.dll",
                        "path": "/cdn/GameAssembly.dll",
                        "hash": "deadbeef",
                        "size": 1,
                    },
                    {
                        "local_path": "\\BepInEx\\core.dll",
                        "path": "/cdn/BepInEx/core.dll",
                        "hash": "deadbeef",
                        "size": 1,
                    },
                ],
            }
        },
    )
    entries, _ = client.get_filelist("tok", "/filelist")
    assert entries[0].local_path == "GameAssembly.dll"
    assert entries[1].local_path == "BepInEx\\core.dll"


def test_get_filelist_accepts_absolute_url(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://other.example.com/list",
        json={"data": {"domain": "d", "file_list": []}},
    )
    entries, domain = client.get_filelist("tok", "https://other.example.com/list")
    assert entries == []
    assert domain == "d"


def test_retries_on_5xx_then_succeeds(client, httpx_mock: HTTPXMock):
    url = f"{BASE}/v5/auth/accesstoken/issue"
    httpx_mock.add_response(method="POST", url=url, status_code=502)
    httpx_mock.add_response(method="POST", url=url, status_code=503)
    httpx_mock.add_response(
        method="POST", url=url, json={"data": {"access_token": "OK"}}
    )
    assert client.issue_token("c") == "OK"


def test_no_retry_on_4xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/accesstoken/issue",
        status_code=400,
        text="bad request",
    )
    with pytest.raises(DmmApiError):
        client.issue_token("c")


def test_raises_after_three_5xx(client, httpx_mock: HTTPXMock):
    url = f"{BASE}/v5/auth/accesstoken/issue"
    for _ in range(3):
        httpx_mock.add_response(method="POST", url=url, status_code=500)
    with pytest.raises(DmmApiError):
        client.issue_token("c")


@pytest.mark.parametrize("code", [300, 314, 399])
def test_launch_raises_game_not_linked_on_3xx_codes(
    client, httpx_mock: HTTPXMock, code: int
):
    """All 3xx server codes are remediated the same way: link the game
    from the official DMM client. We collapse the range under one
    exception so workers can show a single guidance message."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/r2/launch/cl",
        json={"result_code": code, "data": None},
    )
    hwid = HardwareIds("aa:bb:cc:dd:ee:ff", "h", "m")
    with pytest.raises(GameNotLinkedError) as exc_info:
        client.launch_game("tok", "tskx", "ACL", hwid)
    assert "연동" in str(exc_info.value)
    assert str(code) in str(exc_info.value)
    assert "result_code" in exc_info.value.detail


def test_launch_recognizes_3xx_in_nested_error_field(
    client, httpx_mock: HTTPXMock
):
    """Detection works regardless of which common shape the server uses."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/r2/launch/cl",
        json={"error": {"code": 314, "message": "not linked"}, "data": None},
    )
    hwid = HardwareIds("aa:bb:cc:dd:ee:ff", "h", "m")
    with pytest.raises(GameNotLinkedError):
        client.launch_game("tok", "tskx", "ACL", hwid)


@pytest.mark.parametrize("code", [299, 400, 500, 999])
def test_launch_other_codes_remain_generic_dmm_error(
    client, httpx_mock: HTTPXMock, code: int
):
    """Codes outside the recognised bands fall through to the generic
    DmmApiError so we don't mis-route unrelated failures."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/r2/launch/cl",
        json={"result_code": code, "data": None},
    )
    hwid = HardwareIds("aa:bb:cc:dd:ee:ff", "h", "m")
    with pytest.raises(DmmApiError) as exc_info:
        client.launch_game("tok", "tskx", "ACL", hwid)
    assert not isinstance(exc_info.value, GameNotLinkedError)
    assert not isinstance(exc_info.value, AuthInvalidError)


def test_launch_raises_auth_invalid_on_203(client, httpx_mock: HTTPXMock):
    """Code 203 means the bearer token was rejected. UI should prompt
    the user to log out and back in for a fresh token."""
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/r2/launch/cl",
        json={"result_code": 203, "data": None},
    )
    hwid = HardwareIds("aa:bb:cc:dd:ee:ff", "h", "m")
    with pytest.raises(AuthInvalidError) as exc_info:
        client.launch_game("tok", "tskx", "ACL", hwid)
    assert "203" in str(exc_info.value)
    assert exc_info.value.detail


def test_filelist_raises_auth_invalid_on_203(client, httpx_mock: HTTPXMock):
    """Token can also expire between launch and filelist — same dispatch."""
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/filelist",
        json={"result_code": 203, "data": None},
    )
    with pytest.raises(AuthInvalidError):
        client.get_filelist("tok", "/filelist")


def test_filelist_raises_game_not_linked_on_3xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/filelist",
        json={"result_code": 314, "data": None},
    )
    with pytest.raises(GameNotLinkedError):
        client.get_filelist("tok", "/filelist")


def test_raises_on_missing_data_field(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v5/auth/login/url",
        json={"unexpected": "shape"},
    )
    with pytest.raises(DmmApiError):
        client.get_login_url()
