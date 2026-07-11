"""Tests for store.settings.SettingsStore."""

from __future__ import annotations

from shantytown.store.settings import Settings, SettingsStore


def test_default_settings_when_no_file(tmp_path):
    s = SettingsStore(tmp_path / "settings.json")
    assert s.get().theme == "system"


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = SettingsStore(path)
    s.update(Settings(theme="dark"))
    s2 = SettingsStore(path)
    assert s2.get().theme == "dark"


def test_tutorial_completed_defaults_to_false(tmp_path):
    s = SettingsStore(tmp_path / "settings.json")
    assert s.get().tutorial_completed is False


def test_tutorial_completed_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = SettingsStore(path)
    s.update(Settings(theme="light", tutorial_completed=True))
    s2 = SettingsStore(path)
    loaded = s2.get()
    assert loaded.tutorial_completed is True
    assert loaded.theme == "light"


def test_legacy_settings_without_tutorial_field_load_safely(tmp_path):
    """A settings.json written before tutorial_completed existed should
    load with the field defaulted to False — not crash."""
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "settings": {"theme": "dark"}}', encoding="utf-8"
    )
    s = SettingsStore(path)
    loaded = s.get()
    assert loaded.theme == "dark"
    assert loaded.tutorial_completed is False


def test_invalid_theme_falls_back_to_system(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "settings": {"theme": "neon"}}', encoding="utf-8"
    )
    s = SettingsStore(path)
    assert s.get().theme == "system"


def test_login_method_defaults_to_browser(tmp_path):
    s = SettingsStore(tmp_path / "settings.json")
    assert s.get().login_method == "browser"


def test_login_method_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = SettingsStore(path)
    s.update(Settings(theme="dark", login_method="webview"))
    s2 = SettingsStore(path)
    loaded = s2.get()
    assert loaded.login_method == "webview"
    assert loaded.theme == "dark"


def test_invalid_login_method_falls_back_to_browser(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "settings": {"login_method": "carrier-pigeon"}}',
        encoding="utf-8",
    )
    s = SettingsStore(path)
    assert s.get().login_method == "browser"


def test_legacy_settings_without_login_method_load_safely(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "settings": {"theme": "dark"}}', encoding="utf-8"
    )
    s = SettingsStore(path)
    loaded = s.get()
    assert loaded.theme == "dark"
    assert loaded.login_method == "browser"
    assert loaded.auto_login is False


def test_auto_login_defaults_to_false(tmp_path):
    s = SettingsStore(tmp_path / "settings.json")
    assert s.get().auto_login is False


def test_auto_login_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = SettingsStore(path)
    s.update(Settings(login_method="webview", auto_login=True))
    loaded = SettingsStore(path).get()
    assert loaded.auto_login is True
    assert loaded.login_method == "webview"


def test_corrupt_json_backed_up(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    s = SettingsStore(path)
    assert s.get().theme == "system"
    assert path.with_suffix(path.suffix + ".corrupt").is_file()
