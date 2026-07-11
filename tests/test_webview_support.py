"""Tests for gui.webview_support.webview_available."""

from __future__ import annotations

from shantytown.gui.webview_support import webview_available


def test_webview_available_true_in_dev():
    # PyQt6-WebEngine is a dev dependency, so QtWebEngine is importable in
    # the test environment (this mirrors the 'webview' build variant).
    assert webview_available() is True
