"""Tests for core.i18n."""

from __future__ import annotations

from shantytown.core.i18n import (
    EN,
    KO,
    Translator,
    init_translator,
    normalize_lang,
    t,
)


def test_normalize_lang_full_locale_strings():
    assert normalize_lang("ko_KR") == KO
    assert normalize_lang("ko_KR.UTF-8") == KO
    assert normalize_lang("ko-KR") == KO
    assert normalize_lang("KO") == KO
    assert normalize_lang("en_US") == EN
    assert normalize_lang("en") == EN
    # Unknown locales fall back to English.
    assert normalize_lang("ja_JP") == EN
    assert normalize_lang("garbage") == EN


def test_translator_returns_korean_for_known_key():
    tr = Translator(KO)
    assert tr("card.state.ready") == "실행"


def test_translator_returns_english_for_known_key():
    tr = Translator(EN)
    assert tr("card.state.ready") == "Play"


def test_translator_falls_back_to_english_for_unknown_locale():
    tr = Translator("zz")
    assert tr("card.state.ready") == "Play"


def test_translator_returns_key_when_string_unknown():
    tr = Translator(KO)
    assert tr("nonexistent.key.xyz") == "nonexistent.key.xyz"


def test_translator_format_kwargs():
    tr = Translator(KO)
    rendered = tr("card.profile.default", name="alice")
    assert "alice" in rendered


def test_t_uses_active_translator():
    init_translator("en")
    assert t("card.state.ready") == "Play"
    init_translator("ko")
    assert t("card.state.ready") == "실행"


def test_format_silently_falls_back_when_kwargs_missing():
    tr = Translator(KO)
    # Missing kwarg: returns the template as-is rather than raising.
    rendered = tr("worker.error.api")
    assert "DMM API" in rendered or "{error}" in rendered


def test_init_translator_with_explicit_override_wins():
    """``--locale=`` should beat OS detection."""
    tr = init_translator("en")
    assert tr.lang == EN
    tr = init_translator("ko_KR")
    assert tr.lang == KO


def test_init_translator_none_falls_back_to_system():
    """Passing ``None`` triggers OS detection. We can't pin the OS
    locale in tests, but the result must be one of the supported langs."""
    tr = init_translator(None)
    assert tr.lang in (KO, EN)
