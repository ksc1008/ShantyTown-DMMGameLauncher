"""DPAPI-backed encryption for sensitive strings (access tokens).

``CryptProtectData`` ties a ciphertext to the current Windows user
account — different account or different machine = can't decrypt.
This defends against passive token leak (file copy, cloud-sync
backup of ``%APPDATA%``, multi-user PC) at zero UI cost: no UAC
prompt, no admin rights, just a user-mode call into ``crypt32.dll``.

What it does *not* protect against, on purpose:

- Malware running as the same user — it can call ``CryptUnprotectData``
  exactly the same way we do. No client-side scheme defeats this.
- Memory dumps while we're using the token (it's plaintext in process).
- Targeted attackers who can run elevated code on the user's box.

Storage format is a versioned text envelope so:

- Plaintext tokens written by older versions of the app keep loading
  unchanged (no migration step required); they pick up encryption the
  next time the profile is saved.
- Non-Windows hosts (CI, dev linux/mac) don't fail — ``encrypt`` is a
  no-op and stored values round-trip as plaintext.
- ``decrypt`` returns ``""`` on any failure (corrupted blob, user
  account changed, …) so the UI nudges the user to log in again
  rather than crashing.

Second layer — AES against generic infostealers
-----------------------------------------------
A generic infostealer sweeps ``%APPDATA%`` and blindly runs
``CryptUnprotectData`` over every DPAPI blob it finds (it runs as the
user, so DPAPI hands the plaintext right back). To make our profiles
worthless to that automated sweep, :func:`encrypt_secret` wraps the
value in **AES-256-GCM first, then DPAPI** — so peeling DPAPI only
yields more ciphertext. The AES key is derived from the profile's own
id (``shanty_{id}``), which stays plaintext in the file; this is
deliberately *not* a defence against a targeted attacker who reads our
source and the file, only against the blind mass-decrypt sweep. DPAPI
remains the real user-binding boundary; AES is the extra obfuscation on
top.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sys
from ctypes import wintypes

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "dpapi:v1:"

# Inner (AES) envelope marker. A stored secret that survives DPAPI
# decryption and still carries this prefix must be AES-unwrapped; one
# that doesn't is a legacy plaintext / DPAPI-only value and passes
# through untouched (that's what keeps old files loading).
AES_PREFIX = "aes256:gcm:"
_NONCE_LEN = 12  # 96-bit nonce, the AES-GCM standard


def _aes_key(profile_id: str) -> bytes:
    """Derive a 32-byte AES-256 key from the profile id.

    The key material is ``shanty_{id}`` (the id is unique per profile);
    SHA-256 stretches it to the 32 bytes AES-256 needs.
    """
    return hashlib.sha256(f"shanty_{profile_id}".encode()).digest()

# Optional entropy passed to CryptProtectData. Calling
# ``CryptUnprotectData`` without the matching entropy returns failure
# even on the same user account, so a random script can't just feed
# our profile blob into the API and walk away with the token.
_ENTROPY = b"shantytown.profiles.v1"


def is_supported() -> bool:
    """Whether DPAPI calls will actually do something on this host."""
    return sys.platform == "win32"


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` for storage.

    Returns ``"dpapi:v1:<b64>"`` on Windows, the input unchanged on
    other platforms (so tests / non-Windows dev work the same way the
    user would experience without a Windows-specific bootstrap).
    """
    if not plaintext or not is_supported():
        return plaintext
    blob = _crypt_protect(plaintext.encode("utf-8"))
    return PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt(stored: str) -> str:
    """Reverse of :func:`encrypt`.

    A stored value that doesn't carry the marker prefix is treated as
    plaintext — that's how we transparently pick up tokens written by
    older versions of the app.

    Returns ``""`` on any DPAPI failure so callers downgrade gracefully
    to "needs login again" rather than raising.
    """
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored  # legacy plaintext or non-Windows write
    if not is_supported():
        return ""  # encrypted on Windows, can't reverse here
    try:
        blob = base64.b64decode(stored[len(PREFIX):])
    except ValueError:
        return ""
    try:
        return _crypt_unprotect(blob).decode("utf-8")
    except OSError:
        return ""


# --- AES layer (keyed by profile id) ---------------------------------


def aes_encrypt(plaintext: str, profile_id: str) -> str:
    """AES-256-GCM encrypt ``plaintext`` under the ``shanty_{id}`` key.

    Returns ``"aes256:gcm:<b64(nonce+ciphertext)>"``. Empty input is
    returned unchanged so callers can pass optional fields straight
    through. Cross-platform (no Windows dependency).
    """
    if not plaintext:
        return plaintext
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_aes_key(profile_id)).encrypt(
        nonce, plaintext.encode("utf-8"), None
    )
    return AES_PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def aes_decrypt(stored: str, profile_id: str) -> str:
    """Reverse of :func:`aes_encrypt`.

    A value without the ``aes256:gcm:`` marker is treated as already
    unwrapped (legacy plaintext / DPAPI-only) and returned as-is.
    Returns ``""`` on any AES failure (wrong key, tampered blob).
    """
    if not stored or not stored.startswith(AES_PREFIX):
        return stored
    try:
        raw = base64.b64decode(stored[len(AES_PREFIX):])
    except ValueError:
        return ""
    nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        return AESGCM(_aes_key(profile_id)).decrypt(nonce, ct, None).decode(
            "utf-8"
        )
    except (InvalidTag, ValueError):
        return ""


def encrypt_secret(plaintext: str, profile_id: str) -> str:
    """Double-encrypt a profile secret: AES-256-GCM, then DPAPI.

    The AES layer (keyed by the profile id) means a generic infostealer
    that mass-runs ``CryptUnprotectData`` only recovers AES ciphertext.
    On non-Windows the DPAPI step is a no-op, leaving the AES envelope.
    """
    if not plaintext:
        return plaintext
    return encrypt(aes_encrypt(plaintext, profile_id))


def decrypt_secret(stored: str, profile_id: str) -> str:
    """Reverse of :func:`encrypt_secret` — DPAPI first, then AES.

    Handles every prior format transparently via the envelope markers:
    ``dpapi(aes(secret))`` (v2), ``dpapi(secret)`` (v1, DPAPI-only), and
    bare plaintext (pre-DPAPI) all decode to the original secret.
    Returns ``""`` on any failure so the UI prompts a re-login.
    """
    if not stored:
        return ""
    return aes_decrypt(decrypt(stored), profile_id)


# --- ctypes binding --------------------------------------------------


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_crypt32: ctypes.WinDLL | None = None
_kernel32: ctypes.WinDLL | None = None


def _bind() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """Lazy-load and configure the Win32 entry points we need."""
    global _crypt32, _kernel32
    if _crypt32 is not None and _kernel32 is not None:
        return _crypt32, _kernel32
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = crypt32.CryptProtectData.argtypes
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    _crypt32, _kernel32 = crypt32, kernel32
    return crypt32, kernel32


def _make_blob(buffer: ctypes.Array[ctypes.c_char]) -> _DataBlob:
    """Wrap a ctypes string buffer in a DATA_BLOB structure.

    The caller must keep ``buffer`` alive for as long as the blob is
    referenced — DATA_BLOB only holds a pointer.
    """
    return _DataBlob(
        len(buffer.raw),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )


def _crypt_protect(data: bytes) -> bytes:
    if not is_supported():
        raise OSError("DPAPI is not available on this platform")
    crypt32, kernel32 = _bind()

    in_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    in_blob = _make_blob(in_buf)
    ent_blob = _make_blob(ent_buf)
    out_blob = _DataBlob()

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,  # description
        ctypes.byref(ent_blob),
        None,  # reserved
        None,  # prompt struct
        0,  # flags
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(
            f"CryptProtectData failed (GetLastError={ctypes.GetLastError()})"
        )
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    if not is_supported():
        raise OSError("DPAPI is not available on this platform")
    crypt32, kernel32 = _bind()

    in_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    in_blob = _make_blob(in_buf)
    ent_blob = _make_blob(ent_buf)
    out_blob = _DataBlob()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(
            f"CryptUnprotectData failed (GetLastError={ctypes.GetLastError()})"
        )
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
