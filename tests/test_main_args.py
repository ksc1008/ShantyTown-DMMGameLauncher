"""Tests for ``shantytown.__main__._parse_args``."""

from __future__ import annotations

from shantytown.__main__ import _parse_args


def test_parse_args_defaults():
    debug, locale, force_tut, launch_id, qt_argv = _parse_args(["shantytown"])
    assert debug is False
    assert locale is None
    assert force_tut is False
    assert launch_id is None
    assert qt_argv == ["shantytown"]


def test_parse_args_extracts_launch_id():
    _, _, _, launch_id, qt_argv = _parse_args(
        ["shantytown.exe", "--launch=tskx"]
    )
    assert launch_id == "tskx"
    # Qt should not see our flag.
    assert qt_argv == ["shantytown.exe"]


def test_parse_args_empty_launch_treated_as_none():
    """A blank ``--launch=`` (or whitespace-only) should not drop us
    into a launch flow with no product id — defensive against a
    malformed shortcut."""
    _, _, _, launch_id, _ = _parse_args(["shantytown", "--launch="])
    assert launch_id is None
    _, _, _, launch_id, _ = _parse_args(["shantytown", "--launch=   "])
    assert launch_id is None


def test_parse_args_passes_through_qt_flags():
    """Qt's own flags (``-platform offscreen`` etc.) must survive
    untouched so the test runner / headless modes still work."""
    _, _, _, _, qt_argv = _parse_args(
        ["shantytown", "--launch=tskx", "-platform", "offscreen"]
    )
    assert qt_argv == ["shantytown", "-platform", "offscreen"]


def test_parse_args_combined_flags():
    debug, locale, force_tut, launch_id, _ = _parse_args(
        [
            "shantytown",
            "--debug",
            "--locale",
            "ko",
            "--show-tutorial",
            "--launch=tskx",
        ]
    )
    assert debug is True
    assert locale == "ko"
    assert force_tut is True
    assert launch_id == "tskx"
