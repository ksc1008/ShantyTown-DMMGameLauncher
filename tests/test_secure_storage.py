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


# --- AES layer (cross-platform) ---


def test_aes_round_trip():
    original = "secret-tok-한글-混合"
    blob = secure_storage.aes_encrypt(original, "profile-id-1")
    assert blob.startswith(secure_storage.AES_PREFIX)
    assert original not in blob  # not sitting there in plaintext
    assert secure_storage.aes_decrypt(blob, "profile-id-1") == original


def test_aes_empty_passthrough():
    assert secure_storage.aes_encrypt("", "id") == ""
    assert secure_storage.aes_decrypt("", "id") == ""


def test_aes_decrypt_passes_through_unmarked_value():
    # A legacy plaintext / DPAPI-only value has no AES marker → untouched.
    assert secure_storage.aes_decrypt("plain-token", "id") == "plain-token"


def test_aes_nonce_makes_each_ciphertext_unique():
    a = secure_storage.aes_encrypt("same", "id")
    b = secure_storage.aes_encrypt("same", "id")
    assert a != b
    assert secure_storage.aes_decrypt(a, "id") == "same"
    assert secure_storage.aes_decrypt(b, "id") == "same"


def test_aes_wrong_profile_id_fails_to_decrypt():
    """The id is the key — decrypting with a different id must not work."""
    blob = secure_storage.aes_encrypt("secret", "id-A")
    assert secure_storage.aes_decrypt(blob, "id-B") == ""


def test_aes_tampered_blob_returns_empty():
    import base64

    blob = secure_storage.AES_PREFIX + base64.b64encode(b"x" * 40).decode()
    assert secure_storage.aes_decrypt(blob, "id") == ""


# --- double-encrypted secret (AES + DPAPI) ---


def test_encrypt_secret_round_trips():
    original = "super-secret-token"
    blob = secure_storage.encrypt_secret(original, "pid-1")
    assert original not in blob
    assert secure_storage.decrypt_secret(blob, "pid-1") == original


def test_encrypt_secret_empty_passthrough():
    assert secure_storage.encrypt_secret("", "pid") == ""
    assert secure_storage.decrypt_secret("", "pid") == ""


def test_decrypt_secret_handles_legacy_plaintext():
    # Pre-DPAPI plaintext (no markers at all) still decodes to itself.
    assert secure_storage.decrypt_secret("old-plain-token", "pid") == "old-plain-token"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is a Win32 API")
def test_encrypt_secret_is_double_wrapped_on_windows():
    """On Windows the stored value is DPAPI(AES(secret)): the outer layer
    is DPAPI, and peeling it reveals the AES envelope, not the secret."""
    blob = secure_storage.encrypt_secret("my-secret", "pid-1")
    assert blob.startswith(secure_storage.PREFIX)  # outer = DPAPI
    inner = secure_storage.decrypt(blob)  # peel DPAPI only
    assert inner.startswith(secure_storage.AES_PREFIX)  # inner = AES
    assert "my-secret" not in inner  # still ciphertext, not the secret


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is a Win32 API")
def test_decrypt_secret_handles_v1_dpapi_only():
    """A v1 value (DPAPI over the raw secret, no AES) still decrypts —
    that's what makes the v1 → v2 migration read the old file."""
    v1 = secure_storage.encrypt("raw-secret")  # DPAPI-only, no AES
    assert secure_storage.decrypt_secret(v1, "pid-1") == "raw-secret"


# --- non-Windows fallback ---


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows fallback path")
def test_encrypt_is_noop_on_non_windows():
    assert secure_storage.encrypt("token") == "token"


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows fallback path")
def test_marker_decrypt_returns_empty_on_non_windows():
    """A blob produced on Windows can't be decrypted elsewhere — we
    surface that as empty so the UI nudges a re-login."""
    assert secure_storage.decrypt("dpapi:v1:base64stuff==") == ""
