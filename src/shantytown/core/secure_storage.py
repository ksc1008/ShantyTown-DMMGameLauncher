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
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

PREFIX = "dpapi:v1:"

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
