"""Tests for core.download.download_file."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from shantytown.core.download import DownloadProgress, download_file


def test_writes_file_and_calls_progress(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://cdn.example.com/example.bin",
        content=b"hello world",
        headers={"Content-Length": "11"},
    )
    dest = tmp_path / "sub" / "example.bin"
    progress: list[DownloadProgress] = []
    download_file(
        "https://cdn.example.com/example.bin",
        dest,
        progress_cb=progress.append,
    )

    assert dest.read_bytes() == b"hello world"
    assert progress  # at least one tick
    assert progress[-1].bytes_received == 11
    assert progress[-1].total_bytes == 11
    assert progress[-1].file_name == "example.bin"


def test_creates_parent_directories(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url="https://cdn/x", content=b"x")
    dest = tmp_path / "deep" / "nested" / "x"
    download_file("https://cdn/x", dest)
    assert dest.exists()


def test_passes_cookie_header(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url="https://cdn/x", content=b"x")
    download_file("https://cdn/x", tmp_path / "x", cookie="sid=abc")
    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers.get("Cookie") == "sid=abc"


def test_no_cookie_header_when_not_set(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url="https://cdn/x", content=b"x")
    download_file("https://cdn/x", tmp_path / "x")
    req = httpx_mock.get_request()
    assert req is not None
    # httpx may still set generic headers but not "Cookie"
    assert "Cookie" not in req.headers or req.headers["Cookie"] == ""


def test_failure_does_not_leave_partial(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url="https://cdn/x", status_code=500)
    dest = tmp_path / "x"
    with pytest.raises(httpx.HTTPStatusError):
        download_file("https://cdn/x", dest)
    assert not dest.exists()


def test_unknown_content_length(tmp_path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="https://cdn/y",
        content=b"abcdef",
        # no Content-Length header
    )
    progress: list[DownloadProgress] = []
    download_file(
        "https://cdn/y", tmp_path / "y", progress_cb=progress.append
    )
    assert progress
    # total_bytes is None when server doesn't advertise length
    # (httpx may infer it from the body, but we test against the contract:
    # final bytes_received equals what we wrote)
    assert progress[-1].bytes_received == 6
