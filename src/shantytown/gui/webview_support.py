"""Whether webview login is available in this install.

Webview login runs in a separate ``__loginhelper`` process (so the heavy
QtWebEngine payload stays out of the main app). This reports whether
that helper can actually be launched — the shipped ``__loginhelper`` exe
in a frozen build, or the runnable module in dev. It does NOT load
QtWebEngine.

The GUI uses this to hide the webview toggle and force the browser login
flow when the helper isn't present (browser-only install).
"""

from __future__ import annotations


def webview_available() -> bool:
    """True if the webview login helper can be launched (no heavy load)."""
    try:
        from .webview_login_client import helper_command

        return helper_command() is not None
    except Exception:  # pragma: no cover - defensive; never break the UI
        return False
