"""Tests for core.secure_storage.

The DPAPI round-trip tests are gated on Windows since the underlying
``CryptProtectData`` is a Win32 API. The cross-platform tests cover
the format/marker logic that runs on every host.
"""

from __future__ import annotations

import sys

import pytest

from shantytown.core import secure_storage


def test_empty_input_round_trips():
    assert secure_storage.encrypt("") == ""
    assert secure_storage.decrypt("") == ""


def test_legacy_plaintext_passes_through_decrypt():
    """A token written by an older app version has no marker prefix —
    decrypt should return it untouched so users don't have to re-login
    after upgrading."""
    assert secure_storage.decrypt("legacy-plaintext-token") == "legacy-plaintext-token"


def test_decrypt_handles_invalid_base64():
    """Garbage after the marker shouldn't raise — surface as empty."""
    assert secure_storage.decrypt("dpapi:v1:!!!not-base64!!!") == ""


def test_is_supported_matches_platform():
    assert secure_storage.is_supported() == (sys.platform == "win32")


# --- Windows-only round-trip ---


@pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI is a Win32 API"
)
def test_round_trip_preserves_value():
    original = "tok-abcd-1234-한글-混合"
    blob = secure_storage.encrypt(original)
    assert blob.startswith(secure_storage.PREFIX)
    assert secure_storage.decrypt(blob) == original


@pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI is a Win32 API"
)
def test_each_encrypt_produces_a_different_ciphertext():
    """Healthy DPAPI uses random IV — same plaintext encrypts to a
    different blob each call."""
    a = secure_storage.encrypt("same-token")
    b = secure_storage.encrypt("same-token")
    assert a != b
    # ...and both still decrypt back.
    assert secure_storage.decrypt(a) == "same-token"
    assert secure_storage.decrypt(b) == "same-token"


@pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI is a Win32 API"
)
def test_decrypt_corrupted_blob_returns_empty():
    """A blob from another machine / wrong entropy / random bytes
    should fail open as an empty string rather than raise."""
    import base64

    fake = secure_storage.PREFIX + base64.b64encode(b"random-garbage-bytes").decode()
    assert secure_storage.decrypt(fake) == ""


# --- non-Windows fallback ---


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows fallback path")
def test_encrypt_is_noop_on_non_windows():
    assert secure_storage.encrypt("token") == "token"


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows fallback path")
def test_marker_decrypt_returns_empty_on_non_windows():
    """A blob produced on Windows can't be decrypted elsewhere — we
    surface that as empty so the UI nudges a re-login."""
    assert secure_storage.decrypt("dpapi:v1:base64stuff==") == ""
