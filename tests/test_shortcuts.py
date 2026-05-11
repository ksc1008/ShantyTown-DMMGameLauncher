"""Tests for core.shortcuts."""

from __future__ import annotations

import sys

import pytest

from shantytown.core import shortcuts


def test_sanitise_drops_forbidden_chars():
    assert shortcuts._sanitise_filename('hello: world?') == "hello_ world_"
    assert shortcuts._sanitise_filename("a/b\\c") == "a_b_c"


def test_sanitise_blank_falls_back():
    """A name that's empty or pure whitespace/dots after stripping
    falls back to a known-good default — never an empty filename."""
    assert shortcuts._sanitise_filename("") == "Shantytown"
    assert shortcuts._sanitise_filename("    ") == "Shantytown"
    assert shortcuts._sanitise_filename("...") == "Shantytown"


def test_sanitise_keeps_underscore_only_names():
    """Forbidden chars become underscores. ``_`` itself is legal on
    Windows so a name made entirely of them is a valid (if weird)
    filename — we don't second-guess it."""
    assert shortcuts._sanitise_filename("///") == "___"


def test_sanitise_keeps_unicode():
    assert shortcuts._sanitise_filename("판자촌 게임") == "판자촌 게임"


def test_args_string_includes_product_id():
    assert "tskx" in shortcuts._shantytown_args("tskx")
    assert "--launch=tskx" in shortcuts._shantytown_args("tskx")


def test_create_desktop_shortcut_raises_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("Windows-specific guard test")
    with pytest.raises(shortcuts.ShortcutError):
        shortcuts.create_desktop_shortcut(name="x", product_id="tskx")


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows COM shortcut creation"
)
def test_create_desktop_shortcut_round_trip(monkeypatch, tmp_path):
    """Real PowerShell call: create a .lnk, verify it landed."""
    # Redirect "desktop" to a tmp dir so we don't pollute the real one.
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path)
    lnk = shortcuts.create_desktop_shortcut(name="Test Game", product_id="tskx")
    assert lnk.exists()
    assert lnk.suffix == ".lnk"
    assert lnk.parent == tmp_path


def test_icon_uses_game_exe_when_provided(monkeypatch, tmp_path):
    """The PowerShell script must reference the *game* exe in its
    ``IconLocation``, not Shantytown's exe. We capture the script
    by stubbing ``subprocess.run`` and inspecting what would have
    been sent — no real PowerShell call needed."""
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(
        shortcuts, "_shantytown_exe", lambda: tmp_path / "shantytown.exe"
    )
    game_exe = tmp_path / "game.exe"
    game_exe.write_bytes(b"")  # must exist for the icon-path resolver

    captured: dict[str, list[str]] = {}

    def _fake_run(argv, *args, **kwargs):
        captured["argv"] = list(argv)
        # Pretend the .lnk was written so the function returns happily.
        (tmp_path / "Game.lnk").write_bytes(b"")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)
    if sys.platform != "win32":
        # The win32 guard would short-circuit before reaching our stub.
        monkeypatch.setattr(shortcuts.sys, "platform", "win32")

    shortcuts.create_desktop_shortcut(
        name="Game", product_id="tskx", icon_path=game_exe
    )

    script = captured["argv"][-1]
    assert f"IconLocation = '{game_exe},0'" in script
    # And the target is still our exe, not the game's.
    assert f"TargetPath = '{tmp_path / 'shantytown.exe'}'" in script


def test_icon_falls_back_to_shantytown_exe(monkeypatch, tmp_path):
    """No icon path → use Shantytown's own exe so the shortcut still
    has *some* image to display."""
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path)
    fake_exe = tmp_path / "shantytown.exe"
    monkeypatch.setattr(shortcuts, "_shantytown_exe", lambda: fake_exe)

    captured: dict[str, list[str]] = {}

    def _fake_run(argv, *args, **kwargs):
        captured["argv"] = list(argv)
        (tmp_path / "Game.lnk").write_bytes(b"")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)
    if sys.platform != "win32":
        monkeypatch.setattr(shortcuts.sys, "platform", "win32")

    shortcuts.create_desktop_shortcut(name="Game", product_id="tskx")

    script = captured["argv"][-1]
    assert f"IconLocation = '{fake_exe},0'" in script


def test_subprocess_run_uses_no_window_flag(monkeypatch, tmp_path):
    """Frozen ``--windowed`` builds have no parent console, so any
    child ``powershell.exe`` opens its own — visible as a flash for
    the 1-3 s the COM call takes. Pin that we pass
    ``CREATE_NO_WINDOW`` so that doesn't regress."""
    import subprocess

    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(
        shortcuts, "_shantytown_exe", lambda: tmp_path / "shantytown.exe"
    )

    captured_kwargs: dict[str, object] = {}

    def _fake_run(argv, *args, **kwargs):
        captured_kwargs.update(kwargs)
        (tmp_path / "Game.lnk").write_bytes(b"")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    if sys.platform != "win32":
        monkeypatch.setattr(shortcuts.sys, "platform", "win32")

    shortcuts.create_desktop_shortcut(name="Game", product_id="tskx")

    # ``CREATE_NO_WINDOW`` is 0x08000000. Either the symbol exists at
    # runtime (Windows) and we expect that exact value, or it's
    # absent (other platforms / older stubs) and the fallback is 0 —
    # which is fine because no console gets created on those systems
    # anyway. We assert "the flag was passed" rather than equality
    # to a specific number.
    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert captured_kwargs.get("creationflags") == expected


def test_icon_falls_back_when_path_missing(monkeypatch, tmp_path):
    """Caller supplied an icon path but the file doesn't exist (game
    uninstalled, dangling config) — fall through to Shantytown's icon
    rather than producing a shortcut Windows can't render."""
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path)
    fake_exe = tmp_path / "shantytown.exe"
    monkeypatch.setattr(shortcuts, "_shantytown_exe", lambda: fake_exe)

    captured: dict[str, list[str]] = {}

    def _fake_run(argv, *args, **kwargs):
        captured["argv"] = list(argv)
        (tmp_path / "Game.lnk").write_bytes(b"")

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)
    if sys.platform != "win32":
        monkeypatch.setattr(shortcuts.sys, "platform", "win32")

    nonexistent = tmp_path / "no-such-game.exe"
    shortcuts.create_desktop_shortcut(
        name="Game", product_id="tskx", icon_path=nonexistent
    )

    script = captured["argv"][-1]
    assert f"IconLocation = '{fake_exe},0'" in script
    assert str(nonexistent) not in script
