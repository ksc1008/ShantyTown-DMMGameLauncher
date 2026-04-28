"""Read-only loader for the bundled ``known_games.json``.

Known-game metadata is *static*, packaged with the app, and used to
prettify the install list (display name, exe-name hints for the setup
wizard, optional icon URL). It is not user-editable from the GUI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .paths import get_known_games_path


@dataclass(frozen=True)
class KnownGame:
    """One static metadata record."""

    product_id: str
    display_name: str
    exe_name_candidates: tuple[str, ...]
    tags: tuple[str, ...]
    icon_url: str | None


def load_known_games(path: Path | None = None) -> dict[str, KnownGame]:
    """Load the known-games map, keyed by ``product_id``.

    Args:
        path: Override path for tests. Defaults to the bundled resource.
    """
    target = path if path is not None else get_known_games_path()
    raw = json.loads(target.read_text(encoding="utf-8"))
    games_raw = raw.get("games") or {}
    if not isinstance(games_raw, dict):
        raise ValueError("known_games.json: 'games' must be an object")

    result: dict[str, KnownGame] = {}
    for product_id, meta in games_raw.items():
        if not isinstance(meta, dict):
            continue
        result[product_id] = KnownGame(
            product_id=product_id,
            display_name=str(meta.get("displayName", product_id)),
            exe_name_candidates=tuple(
                str(x) for x in meta.get("exeNameCandidates", [])
            ),
            tags=tuple(str(x) for x in meta.get("tags", [])),
            icon_url=(
                str(meta["iconUrl"])
                if isinstance(meta.get("iconUrl"), str)
                else None
            ),
        )
    return result
