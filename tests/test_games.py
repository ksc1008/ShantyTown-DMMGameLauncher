"""Tests for store.games."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shantytown.store.games import GameConfig, GameStore, GameStoreError


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "games.json"


def test_empty_store(store_path):
    s = GameStore(store_path)
    assert s.list() == []
    assert s.get("anything") is None


def test_upsert_inserts_new(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx", exe_path=Path("C:/games/tskx.exe")))
    fetched = s.get("tskx")
    assert fetched is not None
    assert fetched.exe_path == Path("C:/games/tskx.exe")
    assert fetched.profile_id is None
    assert fetched.favorite is False
    assert fetched.last_played_at is None


def test_upsert_replaces_existing(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx", exe_path=Path("C:/old.exe")))
    s.upsert(
        GameConfig(
            product_id="tskx",
            exe_path=Path("C:/new.exe"),
            profile_id="pid-1",
            favorite=True,
        )
    )
    cfg = s.get("tskx")
    assert cfg.exe_path == Path("C:/new.exe")
    assert cfg.profile_id == "pid-1"
    assert cfg.favorite is True


def test_unconfigured_game_round_trips(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx"))  # exe_path=None, all defaults
    s2 = GameStore(store_path)
    cfg = s2.get("tskx")
    assert cfg is not None
    assert cfg.exe_path is None
    assert cfg.profile_id is None


def test_last_played_at_round_trips(store_path):
    s = GameStore(store_path)
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    s.upsert(GameConfig(product_id="tskx", last_played_at=when))
    s2 = GameStore(store_path)
    cfg = s2.get("tskx")
    assert cfg.last_played_at == when


def test_delete(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx"))
    s.delete("tskx")
    assert s.get("tskx") is None
    s2 = GameStore(store_path)
    assert s2.list() == []


def test_delete_unknown_raises(store_path):
    s = GameStore(store_path)
    with pytest.raises(GameStoreError):
        s.delete("no-such-product")


def test_display_name_round_trips(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx", display_name="My Custom Name"))
    s2 = GameStore(store_path)
    cfg = s2.get("tskx")
    assert cfg is not None
    assert cfg.display_name == "My Custom Name"


def test_display_name_defaults_to_none(store_path):
    s = GameStore(store_path)
    s.upsert(GameConfig(product_id="tskx"))
    s2 = GameStore(store_path)
    assert s2.get("tskx").display_name is None


def test_display_name_blank_string_treated_as_none(store_path):
    """Whitespace-only override should be ignored — the user clearing
    the field should bring the bundled / product_id name back, not
    produce a blank title."""
    import json

    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "games": [
                    {
                        "product_id": "tskx",
                        "exe_path": None,
                        "profile_id": None,
                        "favorite": False,
                        "last_played_at": None,
                        "display_name": "   ",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    s = GameStore(store_path)
    assert s.get("tskx").display_name is None


def test_corrupt_json_backed_up(store_path):
    store_path.write_text("not json", encoding="utf-8")
    s = GameStore(store_path)
    assert s.list() == []
    assert store_path.with_suffix(store_path.suffix + ".corrupt").is_file()
