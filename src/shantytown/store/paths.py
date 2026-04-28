"""Application paths.

The user-data root is ``%APPDATA%/shantytown`` on Windows and
``~/.config/shantytown`` everywhere else (so tests on non-Windows CI
don't choke). Directory-returning helpers create the directory on call;
file-returning helpers ensure the *parent* directory exists.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "shantytown"


def get_app_data_dir() -> Path:
    """Return the user-data root, creating it if missing."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    root = base / APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_profiles_path() -> Path:
    """Path to ``profiles.json``. Parent directory is created."""
    return get_app_data_dir() / "profiles.json"


def get_games_path() -> Path:
    """Path to ``games.json``. Parent directory is created."""
    return get_app_data_dir() / "games.json"


def get_settings_path() -> Path:
    """Path to ``settings.json``. Parent directory is created."""
    return get_app_data_dir() / "settings.json"


def get_logs_dir() -> Path:
    """Return the logs directory, creating it if missing."""
    d = get_app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_known_games_path() -> Path:
    """Return the bundled ``known_games.json`` path inside the package.

    Uses ``__file__``-relative resolution, which works for both the
    editable install (uv sync) and a regular wheel install. PyInstaller
    frozen builds will need a different strategy — that's a post-MVP
    concern per ``docs/README.md``.
    """
    return Path(__file__).resolve().parents[1] / "resources" / "known_games.json"
