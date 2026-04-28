"""Tests for store.paths."""

from __future__ import annotations

from pathlib import Path

from shantytown.store import paths


def test_get_app_data_dir_uses_appdata_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = paths.get_app_data_dir()
    assert root == tmp_path / "shantytown"
    assert root.is_dir()


def test_get_profiles_and_games_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.get_profiles_path() == tmp_path / "shantytown" / "profiles.json"
    assert paths.get_games_path() == tmp_path / "shantytown" / "games.json"


def test_get_logs_dir_is_created(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    logs = paths.get_logs_dir()
    assert logs == tmp_path / "shantytown" / "logs"
    assert logs.is_dir()


def test_get_known_games_path_points_to_bundled_resource():
    p = paths.get_known_games_path()
    assert p.name == "known_games.json"
    assert p.is_file()
    # Sanity: it should sit inside the package resources folder.
    assert p.parent.name == "resources"


def test_falls_back_when_appdata_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = paths.get_app_data_dir()
    assert root == tmp_path / ".config" / "shantytown"
    assert root.is_dir()
