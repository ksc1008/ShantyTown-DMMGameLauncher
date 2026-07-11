"""Runtime debug-mode flag.

Toggled by the ``--debug`` command-line flag (parsed in ``__main__.py``)
which sets ``SHANTYTOWN_DEBUG=1``. We use an env var rather than a
module-level boolean so worker threads, late imports, and subprocess
helpers can all read the same source.
"""

from __future__ import annotations

import os

DEBUG_ENV = "SHANTYTOWN_DEBUG"
SHOW_WEBVIEW_ENV = "SHANTYTOWN_SHOW_WEBVIEW"


def _flag(env: str) -> bool:
    val = os.environ.get(env, "")
    return val.lower() not in {"", "0", "false", "no"}


def is_debug() -> bool:
    """True when the ``--debug`` flag was passed at startup."""
    return _flag(DEBUG_ENV)


def show_webview() -> bool:
    """True when ``--show-webview`` was passed — reveal the login webview.

    A debugging aid: the headless login agent normally keeps its Chromium
    off-screen. With this on, the window is shown so a developer can watch
    the login (and solve an interactive reCAPTCHA / 2FA challenge by hand).
    """
    return _flag(SHOW_WEBVIEW_ENV)
