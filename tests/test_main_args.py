"""Tests for ``shantytown.__main__._parse_args``."""

from __future__ import annotations

import sys

from shantytown.__main__ import _ensure_std_streams, _parse_args


def test_parse_args_defaults():
    debug, locale, force_tut, launch_id, show_webview, qt_argv = _parse_args(
        ["shantytown"]
    )
    assert debug is False
    assert locale is None
    assert force_tut is False
    assert launch_id is None
    assert show_webview is False
    assert qt_argv == ["shantytown"]


def test_parse_args_extracts_launch_id():
    *_, launch_id, _show_webview, qt_argv = _parse_args(
        ["shantytown.exe", "--launch=tskx"]
    )
    assert launch_id == "tskx"
    # Qt should not see our flag.
    assert qt_argv == ["shantytown.exe"]


def test_parse_args_empty_launch_treated_as_none():
    """A blank ``--launch=`` (or whitespace-only) should not drop us
    into a launch flow with no product id — defensive against a
    malformed shortcut."""
    *_, launch_id, _sw, _qt = _parse_args(["shantytown", "--launch="])
    assert launch_id is None
    *_, launch_id, _sw, _qt = _parse_args(["shantytown", "--launch=   "])
    assert launch_id is None


def test_parse_args_passes_through_qt_flags():
    """Qt's own flags (``-platform offscreen`` etc.) must survive
    untouched so the test runner / headless modes still work."""
    *_, qt_argv = _parse_args(
        ["shantytown", "--launch=tskx", "-platform", "offscreen"]
    )
    assert qt_argv == ["shantytown", "-platform", "offscreen"]


def test_parse_args_show_webview():
    *_, show_webview, qt_argv = _parse_args(["shantytown", "--show-webview"])
    assert show_webview is True
    assert qt_argv == ["shantytown"]


def test_ensure_std_streams_noop_when_present():
    """Real console streams (dev/test) must be left untouched."""
    before_out, before_err = sys.stdout, sys.stderr
    _ensure_std_streams(debug=False)
    assert sys.stdout is before_out
    assert sys.stderr is before_err


def test_ensure_std_streams_replaces_none_without_debug(monkeypatch):
    """Windowed build (stdout/stderr None) must get safe, writable sinks."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    _ensure_std_streams(debug=False)
    assert sys.stdout is not None
    assert sys.stderr is not None
    # Writing must not raise (this is exactly what crashed before).
    sys.stderr.write("no crash\n")
    sys.stdout.write("no crash\n")


def test_ensure_std_streams_debug_writes_to_logfile(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    _ensure_std_streams(debug=True)
    sys.stderr.write("hello-debug\n")
    sys.stderr.flush()
    log = tmp_path / "shantytown" / "logs" / "debug.log"
    assert log.is_file()
    assert "hello-debug" in log.read_text(encoding="utf-8")


def test_parse_args_combined_flags():
    debug, locale, force_tut, launch_id, show_webview, _qt = _parse_args(
        [
            "shantytown",
            "--debug",
            "--locale",
            "ko",
            "--show-tutorial",
            "--launch=tskx",
            "--show-webview",
        ]
    )
    assert debug is True
    assert locale == "ko"
    assert force_tut is True
    assert launch_id == "tskx"
    assert show_webview is True
