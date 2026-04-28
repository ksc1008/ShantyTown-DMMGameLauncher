"""Tests for core.telemetry — gated by env vars, must not raise."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from shantytown.core import telemetry


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv(telemetry.TELEMETRY_FLAG_ENV, raising=False)
    monkeypatch.delenv(telemetry.TELEMETRY_ENDPOINT_ENV, raising=False)


def test_disabled_when_flag_missing(monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://x")
    assert telemetry.is_enabled() is False


def test_disabled_when_endpoint_missing(monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "1")
    assert telemetry.is_enabled() is False


def test_disabled_when_flag_falsy(monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "0")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://x")
    assert telemetry.is_enabled() is False


def test_enabled_when_both_set(monkeypatch):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "1")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://x")
    assert telemetry.is_enabled() is True


def test_report_no_op_when_disabled(monkeypatch, tmp_path, httpx_mock: HTTPXMock):
    # No flag set. The httpx_mock will fail the test if any HTTP call
    # is made (no responses queued).
    install = tmp_path
    exe = install / "game.exe"
    exe.write_bytes(b"")
    telemetry.report_exe_path("tskx", exe, install)
    assert httpx_mock.get_requests() == []


def test_report_sends_relative_path_when_enabled(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock
):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "1")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://t.example.com/log")
    httpx_mock.add_response(method="POST", url="https://t.example.com/log")

    install = tmp_path / "install"
    (install / "bin").mkdir(parents=True)
    exe = install / "bin" / "game.exe"
    exe.write_bytes(b"")
    telemetry.report_exe_path("tskx", exe, install)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    import json as _json

    body = _json.loads(requests[0].content)
    assert body["product_id"] == "tskx"
    assert body["exe_name"] == "game.exe"
    # Path normalization is OS-dependent — accept either separator.
    assert body["exe_relative_path"].replace("\\", "/") == "bin/game.exe"


def test_report_swallows_network_errors(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock
):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "1")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://t.example.com/log")
    import httpx as _httpx

    httpx_mock.add_exception(_httpx.ConnectError("nope"))
    install = tmp_path
    exe = install / "g.exe"
    exe.write_bytes(b"")
    # Must not raise.
    telemetry.report_exe_path("tskx", exe, install)


def test_report_uses_basename_when_outside_install_dir(
    monkeypatch, tmp_path, httpx_mock: HTTPXMock
):
    monkeypatch.setenv(telemetry.TELEMETRY_FLAG_ENV, "1")
    monkeypatch.setenv(telemetry.TELEMETRY_ENDPOINT_ENV, "https://t.example.com/log")
    httpx_mock.add_response(method="POST", url="https://t.example.com/log")

    install = tmp_path / "install"
    install.mkdir()
    exe = tmp_path / "elsewhere" / "g.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    telemetry.report_exe_path("tskx", exe, install)

    import json as _json

    body = _json.loads(httpx_mock.get_requests()[0].content)
    assert body["exe_relative_path"] == "g.exe"
