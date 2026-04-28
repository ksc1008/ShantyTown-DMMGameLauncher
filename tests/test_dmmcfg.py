"""Tests for core.dmmcfg."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shantytown.core.dmmcfg import parse_dmmgame_cnf

FIXTURE = Path(__file__).parent / "fixtures" / "dmmgame.cnf.sample"


def test_parses_five_installed_games():
    games = parse_dmmgame_cnf(FIXTURE)
    assert len(games) == 5
    assert {g.product_id for g in games} == {
        "muv_luv_girlsgardenx_cl",
        "tskx",
        "dotabyss_x_cl",
        "girlscreation_r",
        "rlyehshoujotaix_cl",
    }


def test_field_mapping_for_tskx():
    games = parse_dmmgame_cnf(FIXTURE)
    tskx = next(g for g in games if g.product_id == "tskx")
    assert tskx.game_type == "ACL"
    assert tskx.version == "01.02.122"
    assert tskx.install_path == Path(
        "C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\Twinkle_StarKnightsX"
    )


def test_skips_uninstalled(tmp_path):
    cnf = tmp_path / "cnf.json"
    cnf.write_text(
        json.dumps(
            {
                "contents": [
                    {
                        "productId": "yes",
                        "gameType": "ACL",
                        "detail": {
                            "installed": True,
                            "path": "C:/yes",
                            "version": "1",
                        },
                    },
                    {
                        "productId": "no",
                        "gameType": "ACL",
                        "detail": {
                            "installed": False,
                            "path": "C:/no",
                            "version": "1",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    games = parse_dmmgame_cnf(cnf)
    assert [g.product_id for g in games] == ["yes"]


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_dmmgame_cnf(Path("does-not-exist.json"))


def test_invalid_json_raises_value_error(tmp_path):
    cnf = tmp_path / "broken.json"
    cnf.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_dmmgame_cnf(cnf)
