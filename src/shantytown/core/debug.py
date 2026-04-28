"""Runtime debug-mode flag.

Toggled by the ``--debug`` command-line flag (parsed in ``__main__.py``)
which sets ``SHANTYTOWN_DEBUG=1``. We use an env var rather than a
module-level boolean so worker threads, late imports, and subprocess
helpers can all read the same source.
"""

from __future__ import annotations

import os

DEBUG_ENV = "SHANTYTOWN_DEBUG"


def is_debug() -> bool:
    """True when the ``--debug`` flag was passed at startup."""
    val = os.environ.get(DEBUG_ENV, "")
    return val.lower() not in {"", "0", "false", "no"}
