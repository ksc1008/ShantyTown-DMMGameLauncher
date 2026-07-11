"""App-wide settings (theme, etc).

Single document, not a list — so the API is just ``get()`` and
``update()``. We use the same atomic-write + corrupt-backup pattern as
the other stores so a bad save can't brick the app.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CURRENT_VERSION = 1

ThemeMode = Literal["system", "light", "dark"]
_VALID_THEMES: frozenset[str] = frozenset({"system", "light", "dark"})

# How the app collects a DMM credential when a profile needs to log in.
# "browser" is the current external-browser + clipboard flow; "webview"
# is the in-app credential form. Default stays "browser" — the webview
# path is opt-in (and today only surfaced behind --debug).
LoginMethod = Literal["browser", "webview"]
_VALID_LOGIN_METHODS: frozenset[str] = frozenset({"browser", "webview"})


@dataclass
class Settings:
    theme: ThemeMode = "system"
    tutorial_completed: bool = False
    login_method: LoginMethod = "browser"
    # Only meaningful with the webview login method. When on: a login with
    # saved credentials submits automatically (no button click), and an
    # expired-token launch auto-logs-out and re-logs-in without prompting.
    auto_login: bool = False


@dataclass
class _Document:
    version: int = CURRENT_VERSION
    settings: Settings = field(default_factory=Settings)


class SettingsStore:
    """JSON-backed single-document settings store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._doc = self._load()

    def get(self) -> Settings:
        return Settings(
            theme=self._doc.settings.theme,
            tutorial_completed=self._doc.settings.tutorial_completed,
            login_method=self._doc.settings.login_method,
            auto_login=self._doc.settings.auto_login,
        )

    def update(self, settings: Settings) -> None:
        self._doc.settings = Settings(
            theme=settings.theme,
            tutorial_completed=settings.tutorial_completed,
            login_method=settings.login_method,
            auto_login=settings.auto_login,
        )
        self._save()

    # --- internals ---

    def _load(self) -> _Document:
        if not self._path.exists():
            return _Document()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object at the root")
        except (json.JSONDecodeError, ValueError, OSError):
            self._backup_corrupted()
            return _Document()

        version = int(raw.get("version", CURRENT_VERSION))
        s_raw = raw.get("settings") or {}
        if not isinstance(s_raw, dict):
            s_raw = {}
        theme_raw = s_raw.get("theme", "system")
        theme: ThemeMode = theme_raw if theme_raw in _VALID_THEMES else "system"
        tutorial_completed = bool(s_raw.get("tutorial_completed", False))
        method_raw = s_raw.get("login_method", "browser")
        login_method: LoginMethod = (
            method_raw if method_raw in _VALID_LOGIN_METHODS else "browser"
        )
        auto_login = bool(s_raw.get("auto_login", False))
        return _Document(
            version=version,
            settings=Settings(
                theme=theme,
                tutorial_completed=tutorial_completed,
                login_method=login_method,
                auto_login=auto_login,
            ),
        )

    def _backup_corrupted(self) -> None:
        if not self._path.exists():
            return
        backup = self._path.with_suffix(self._path.suffix + ".corrupt")
        try:
            os.replace(self._path, backup)
        except OSError:
            pass

    def _save(self) -> None:
        payload: dict[str, Any] = {
            "version": self._doc.version,
            "settings": {
                "theme": self._doc.settings.theme,
                "tutorial_completed": self._doc.settings.tutorial_completed,
                "login_method": self._doc.settings.login_method,
                "auto_login": self._doc.settings.auto_login,
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self._path)
