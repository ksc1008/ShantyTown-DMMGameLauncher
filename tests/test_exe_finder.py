"""Tests for core.exe_finder."""

from __future__ import annotations

from pathlib import Path

from shantytown.core.exe_finder import find_exe_candidate


def test_finds_top_level(tmp_path):
    target = tmp_path / "game.exe"
    target.write_bytes(b"")
    (tmp_path / "other.txt").write_bytes(b"")
    assert find_exe_candidate(tmp_path, ("game.exe",)) == target


def test_finds_nested(tmp_path):
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    target = nested / "thegame.exe"
    target.write_bytes(b"")
    assert find_exe_candidate(tmp_path, ("thegame.exe",)) == target


def test_case_insensitive(tmp_path):
    target = tmp_path / "Game.EXE"
    target.write_bytes(b"")
    assert find_exe_candidate(tmp_path, ("game.exe",)) == target


def test_none_when_missing(tmp_path):
    (tmp_path / "wrongname.exe").write_bytes(b"")
    assert find_exe_candidate(tmp_path, ("game.exe",)) is None


def test_empty_candidates(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"")
    assert find_exe_candidate(tmp_path, ()) is None


def test_missing_dir():
    assert find_exe_candidate(Path("/no/such/dir"), ("x.exe",)) is None
