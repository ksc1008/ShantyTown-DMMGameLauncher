"""Optional telemetry — only active when explicitly enabled.

When a user picks an exe for one of their installed games, we *can*
send the relative path back to a configured endpoint so we can improve
``known_games.json`` defaults over time. This is opt-in via two
environment variables:

- ``SHANTYTOWN_TELEMETRY=1`` — feature flag; must be truthy.
- ``SHANTYTOWN_TELEMETRY_ENDPOINT=https://...`` — destination URL.

If either is missing, ``report_exe_path`` is a no-op and no network
call is made. Failures during the call are silently swallowed —
telemetry must never affect the user-facing flow.

The payload is intentionally minimal: product id and the *relative*
path/name of the exe. Absolute paths and machine identifiers are not
sent.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

TELEMETRY_FLAG_ENV = "SHANTYTOWN_TELEMETRY"
TELEMETRY_ENDPOINT_ENV = "SHANTYTOWN_TELEMETRY_ENDPOINT"


def is_enabled() -> bool:
    """True only when both the flag and the endpoint are configured."""
    flag = os.environ.get(TELEMETRY_FLAG_ENV, "")
    endpoint = os.environ.get(TELEMETRY_ENDPOINT_ENV, "")
    return bool(flag) and flag.lower() not in {"0", "false", "no"} and bool(endpoint)


def _relative_or_name(exe_path: Path, install_dir: Path) -> str:
    try:
        return str(exe_path.resolve().relative_to(install_dir.resolve()))
    except (ValueError, OSError):
        return exe_path.name


def report_exe_path(
    product_id: str,
    exe_path: Path,
    install_dir: Path,
    *,
    timeout: float = 5.0,
) -> None:
    """Best-effort report of a configured exe path.

    No-op if telemetry is disabled. Errors during the HTTP call are
    swallowed — this function must never raise into the GUI thread.
    """
    if not is_enabled():
        return
    endpoint = os.environ[TELEMETRY_ENDPOINT_ENV]
    payload = {
        "product_id": product_id,
        "exe_name": exe_path.name,
        "exe_relative_path": _relative_or_name(exe_path, install_dir),
    }
    try:
        httpx.post(endpoint, json=payload, timeout=timeout)
    except (httpx.HTTPError, OSError):
        # Silent failure is the contract.
        pass
