"""Per-game user configuration.

Tracks the user's chosen exe, optional profile override, favorite
status, and last-played timestamp. Profile assignment is what enables
the "different DMM accounts per game" headline feature: a ``profile_id``
of ``None`` means "use the store's current default profile."
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CURRENT_VERSION = 1


@dataclass
class GameConfig:
    """User-controlled settings for one game.

    ``exe_path = None`` means "not yet configured" — the game card in
    the GUI shows a "setup needed" badge and clicks open the wizard.
    ``profile_id = None`` means "use the default profile."
    """

    product_id: str
    exe_path: Path | None = None
    profile_id: str | None = None
    favorite: bool = False
    last_played_at: datetime | None = None


class GameStoreError(RuntimeError):
    """Raised on store operations that violate invariants (missing id, etc)."""


class GameStore:
    """JSON-backed CRUD for per-game configs, keyed by product_id."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._configs: dict[str, GameConfig] = self._load()

    # --- public API ---

    def list(self) -> list[GameConfig]:
        return list(self._configs.values())

    def get(self, product_id: str) -> GameConfig | None:
        return self._configs.get(product_id)

    def upsert(self, config: GameConfig) -> None:
        """Insert or replace by ``product_id``."""
        self._configs[config.product_id] = config
        self._save()

    def delete(self, product_id: str) -> None:
        if product_id not in self._configs:
            raise GameStoreError(f"game not found: {product_id}")
        del self._configs[product_id]
        self._save()

    # --- internals ---

    def _load(self) -> dict[str, GameConfig]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object at the root")
            entries = raw.get("games", [])
            if not isinstance(entries, list):
                raise ValueError("'games' must be an array")
        except (json.JSONDecodeError, ValueError, TypeError, OSError):
            self._backup_corrupted()
            return {}

        result: dict[str, GameConfig] = {}
        for entry in entries:
            try:
                cfg = self._dict_to_config(entry)
            except (KeyError, ValueError, TypeError):
                continue
            result[cfg.product_id] = cfg
        return result

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
            "version": CURRENT_VERSION,
            "games": [self._config_to_dict(c) for c in self._configs.values()],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self._path)

    @staticmethod
    def _config_to_dict(c: GameConfig) -> dict[str, Any]:
        return {
            "product_id": c.product_id,
            "exe_path": str(c.exe_path) if c.exe_path else None,
            "profile_id": c.profile_id,
            "favorite": c.favorite,
            "last_played_at": (
                c.last_played_at.isoformat() if c.last_played_at else None
            ),
        }

    @staticmethod
    def _dict_to_config(d: object) -> GameConfig:
        if not isinstance(d, dict):
            raise TypeError("game entry must be a JSON object")
        exe_raw = d.get("exe_path")
        last_played_raw = d.get("last_played_at")
        return GameConfig(
            product_id=str(d["product_id"]),
            exe_path=Path(str(exe_raw)) if exe_raw else None,
            profile_id=(
                d.get("profile_id") if isinstance(d.get("profile_id"), str) else None
            ),
            favorite=bool(d.get("favorite", False)),
            last_played_at=(
                datetime.fromisoformat(str(last_played_raw))
                if last_played_raw
                else None
            ),
        )
