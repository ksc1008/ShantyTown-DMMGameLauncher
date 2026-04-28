"""Tests for store.known_games."""

from __future__ import annotations

import json

from shantytown.store.known_games import load_known_games

EXPECTED_PRODUCT_IDS = {
    "tskx",
    "muv_luv_girlsgardenx_cl",
    "dotabyss_x_cl",
    "girlscreation_r",
    "rlyehshoujotaix_cl",
}


def test_loads_five_known_games_from_bundled_resource():
    games = load_known_games()
    assert set(games.keys()) == EXPECTED_PRODUCT_IDS


def test_tskx_has_expected_metadata():
    games = load_known_games()
    tskx = games["tskx"]
    assert tskx.display_name == "Twinkle☆Star Knights X"
    assert "twinkle_starknightsx.exe" in tskx.exe_name_candidates
    assert "RPG" in tskx.tags


def test_load_with_explicit_path(tmp_path):
    p = tmp_path / "kg.json"
    p.write_text(
        json.dumps(
            {
                "games": {
                    "x": {
                        "displayName": "X",
                        "exeNameCandidates": ["x.exe"],
                        "tags": ["t"],
                        "iconUrl": "https://example.com/x.png",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    games = load_known_games(p)
    assert list(games.keys()) == ["x"]
    assert games["x"].icon_url == "https://example.com/x.png"
    assert games["x"].exe_name_candidates == ("x.exe",)
    assert games["x"].tags == ("t",)


def test_empty_games_object_yields_empty_dict(tmp_path):
    p = tmp_path / "kg.json"
    p.write_text(json.dumps({"games": {}}), encoding="utf-8")
    assert load_known_games(p) == {}
