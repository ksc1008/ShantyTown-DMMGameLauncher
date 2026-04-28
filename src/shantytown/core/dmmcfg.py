"""Read the official DMM Game Player config (``dmmgame.cnf``).

This file is the single source of truth for *which games are installed*.
The launcher treats it as read-only: installing a new game is the
official client's job, and once it shows up here we can use it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import InstalledGame


def get_default_cnf_path() -> Path:
    """Return ``%APPDATA%/dmmgameplayer5/dmmgame.cnf`` on Windows."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable is not set.")
    return Path(appdata) / "dmmgameplayer5" / "dmmgame.cnf"


def parse_dmmgame_cnf(path: Path) -> list[InstalledGame]:
    """Parse ``dmmgame.cnf`` and return only the installed entries.

    Args:
        path: Path to ``dmmgame.cnf``.

    Returns:
        One ``InstalledGame`` per ``contents`` entry whose
        ``detail.installed`` is ``True``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or has an unexpected shape.
    """
    if not path.exists():
        raise FileNotFoundError(f"dmmgame.cnf not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"dmmgame.cnf is not valid JSON ({path}): {e}") from e

    contents = raw.get("contents")
    if not isinstance(contents, list):
        raise ValueError("dmmgame.cnf is missing a 'contents' array.")

    games: list[InstalledGame] = []
    for entry in contents:
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict) or not detail.get("installed", False):
            continue
        product_id = entry.get("productId")
        game_type = entry.get("gameType")
        install_path = detail.get("path")
        if not isinstance(product_id, str) or not isinstance(game_type, str):
            continue
        if not isinstance(install_path, str) or not install_path:
            continue
        version = detail.get("version", "")
        games.append(
            InstalledGame(
                product_id=product_id,
                game_type=game_type,
                install_path=Path(install_path),
                version=str(version),
            )
        )
    return games
