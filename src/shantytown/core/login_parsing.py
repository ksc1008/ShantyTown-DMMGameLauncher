"""Qt-free parsing helpers for the DMM login flow.

This is the **single place** that knows the shape of DMM's login page
and redirect. The webview agent only shovels raw strings (the redirect
URL, the ``__NEXT_DATA__`` JSON text) in here; all fragile
DMM-structure knowledge lives in this module so a page change can be
fixed by editing one file (requirement: HTML parsing must be tightly
modularised).

Two things it extracts:

- ``extract_code`` — the OAuth ``code`` from the post-login redirect,
  which DMM delivers as a custom-scheme URL like
  ``dmmgameplayer5://...?code=abc``.
- ``login_error_messages`` — the server-side error strings DMM embeds
  in the page's ``__NEXT_DATA__`` JSON (``props.pageProps.error``). On a
  successful credential POST this array is empty; on a bad password it
  holds e.g. ``"メールアドレスまたはパスワードが正しくありません。"``. Reading
  the structured JSON is far more robust than scraping the visible
  alert element's CSS-hashed classes.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

_CODE_RE = re.compile(r"[?&]code=([^&\s]+)")

# DMM's post-login redirect. The ``code`` is delivered *in the URL itself*
# (no response body) via a normal HTTPS navigation to
# ``https://webdgp-gameplayer.games.dmm.com/login/success?code=<token>``.
# Older/other flows may instead redirect to the custom scheme
# ``dmmgameplayer5://...?code=`` — we recognise both.
_REDIRECT_SCHEME = "dmmgameplayer5"
_REDIRECT_HOST_SUFFIX = "gameplayer.games.dmm.com"
_REDIRECT_PATH = "/login/success"


def is_login_redirect(url: str) -> bool:
    """True if ``url`` is DMM's post-login redirect carrying the ``code``.

    Matches the custom scheme *and* the HTTPS success URL — the login
    completes by navigating to a URL, not by returning a response body,
    so the agent watches for this to know it's done.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme == _REDIRECT_SCHEME:
        return True
    host = (parsed.hostname or "").lower()
    return (
        host.endswith(_REDIRECT_HOST_SUFFIX)
        and _REDIRECT_PATH in parsed.path
        and "code=" in (parsed.query or "")
    )
# Pulls the JSON body out of ``<script id="__NEXT_DATA__" ...>...</script>``.
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def extract_code(text: str) -> str | None:
    """Pull the OAuth ``code`` parameter out of ``text`` if present.

    Accepts both well-formed URLs (``https://...?code=abc``) and
    custom-scheme URLs (``dmmgameplayer5://...?code=abc``). Returns
    ``None`` if no code is found.
    """
    if not text:
        return None
    text = text.strip()
    # Try proper URL parsing first — handles encoded values cleanly.
    try:
        parsed = urlparse(text)
        if parsed.query:
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            if code:
                return code
    except ValueError:
        pass
    # Fallback regex — works on bare query fragments and odd shapes.
    m = _CODE_RE.search(text)
    if m:
        return m.group(1)
    return None


def parse_next_data(text: str) -> dict[str, Any] | None:
    """Parse DMM's ``__NEXT_DATA__`` payload from raw JSON or full HTML.

    ``text`` may be the JSON string itself (what the agent reads via
    ``document.getElementById('__NEXT_DATA__').textContent``) or a whole
    HTML document. Returns the decoded object, or ``None`` if it can't
    be found/parsed.
    """
    if not text:
        return None
    candidate = text.strip()
    if not candidate.startswith("{"):
        m = _NEXT_DATA_RE.search(text)
        if not m:
            return None
        candidate = m.group(1).strip()
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def login_error_messages(text: str) -> list[str]:
    """Return the server-side login errors, empty list if the POST was OK.

    ``text`` is the ``__NEXT_DATA__`` JSON (or full HTML). Reads
    ``props.pageProps.error`` — a list of human-readable messages DMM
    renders on a failed credential submit.
    """
    data = parse_next_data(text)
    if data is None:
        return []
    cur: Any = data
    for key in ("props", "pageProps", "error"):
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    if isinstance(cur, list):
        return [str(e) for e in cur if e]
    return []
