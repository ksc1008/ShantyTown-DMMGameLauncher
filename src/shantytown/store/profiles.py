"""Profile persistence.

A *profile* is a named DMM account: a UUID, a display name, an optional
access token, and an optional auto-discovered email. The store keeps a
``default_profile_id`` that games fall back to when they don't have an
explicit assignment.

Default-profile rules (per the product spec, not the original doc):
- The first profile created is automatically promoted to default.
- Deleting the default reassigns default to the first remaining
  profile, or ``None`` if the store is now empty.
- ``set_default`` on a non-existent id raises ``ProfileStoreError``.

Tokens are encrypted via Windows DPAPI (see
``shantytown.core.secure_storage``) on save and decrypted on load.
Plaintext tokens written by older versions of the app keep loading
unchanged — they pick up encryption the next time the profile is
saved, so no explicit migration step is required.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shantytown.core import secure_storage

CURRENT_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Profile:
    """One DMM account stored in the profile store."""

    id: str
    name: str
    token: str | None
    created_at: datetime
    last_used_at: datetime | None = None
    email: str | None = None
    # Saved DMM login password for the webview login flow. Encrypted at
    # rest via DPAPI (same envelope as ``token``); ``None`` when the user
    # hasn't entered credentials for the in-app form.
    password: str | None = None


class ProfileStoreError(RuntimeError):
    """Raised on store operations that violate invariants (missing id, etc)."""


@dataclass
class _StoreData:
    version: int
    default_profile_id: str | None
    profiles: list[Profile] = field(default_factory=list)


class ProfileStore:
    """JSON-backed CRUD for profiles. Single-process, not thread-safe."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # ``_load`` flips ``_has_plaintext_tokens`` to True if any
        # token in the file lacks the DPAPI marker. We use that to
        # trigger an immediate re-save below so existing users get
        # their tokens encrypted at rest on the very next boot after
        # upgrading — without waiting for a profile mutation.
        self._has_plaintext_tokens = False
        self._data = self._load()
        if secure_storage.is_supported() and self._has_plaintext_tokens:
            self._save()

    # --- public API ---

    def list(self) -> list[Profile]:
        """Return a shallow copy of all profiles in insertion order."""
        return list(self._data.profiles)

    def get(self, profile_id: str) -> Profile | None:
        for p in self._data.profiles:
            if p.id == profile_id:
                return p
        return None

    def create(
        self,
        name: str,
        *,
        token: str | None = None,
        email: str | None = None,
    ) -> Profile:
        """Create and persist a new profile.

        Auto-promotes the new profile to default if the store has no
        default yet.
        """
        profile = Profile(
            id=str(uuid.uuid4()),
            name=name,
            token=token,
            created_at=_utcnow(),
            last_used_at=None,
            email=email,
        )
        self._data.profiles.append(profile)
        if self._data.default_profile_id is None:
            self._data.default_profile_id = profile.id
        self._save()
        return profile

    def update(self, profile: Profile) -> None:
        """Replace the matching profile and persist. Raises if id is unknown."""
        for i, existing in enumerate(self._data.profiles):
            if existing.id == profile.id:
                self._data.profiles[i] = profile
                self._save()
                return
        raise ProfileStoreError(f"profile not found: {profile.id}")

    def delete(self, profile_id: str) -> None:
        """Delete the profile and reassign default if needed."""
        before = len(self._data.profiles)
        self._data.profiles = [p for p in self._data.profiles if p.id != profile_id]
        if len(self._data.profiles) == before:
            raise ProfileStoreError(f"profile not found: {profile_id}")
        if self._data.default_profile_id == profile_id:
            self._data.default_profile_id = (
                self._data.profiles[0].id if self._data.profiles else None
            )
        self._save()

    def get_default(self) -> Profile | None:
        if self._data.default_profile_id is None:
            return None
        return self.get(self._data.default_profile_id)

    def set_default(self, profile_id: str) -> None:
        if self.get(profile_id) is None:
            raise ProfileStoreError(f"profile not found: {profile_id}")
        self._data.default_profile_id = profile_id
        self._save()

    # --- internals ---

    def _load(self) -> _StoreData:
        if not self._path.exists():
            return _StoreData(
                version=CURRENT_VERSION, default_profile_id=None, profiles=[]
            )
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object at the root")
            raw_profiles = raw.get("profiles", [])
            # Inspect raw token strings BEFORE _dict_to_profile decrypts
            # them, so we can tell whether the file on disk holds any
            # legacy plaintext tokens (no ``dpapi:v1:`` marker). The
            # ``__init__`` caller uses the flag to schedule a one-shot
            # re-save that migrates them to encrypted form.
            for entry in raw_profiles:
                if not isinstance(entry, dict):
                    continue
                secrets = (entry.get("token"), entry.get("password"))
                if any(
                    isinstance(s, str)
                    and s
                    and not s.startswith(secure_storage.PREFIX)
                    for s in secrets
                ):
                    self._has_plaintext_tokens = True
                    break
            profiles = [self._dict_to_profile(p) for p in raw_profiles]
        except (json.JSONDecodeError, ValueError, TypeError, KeyError, OSError):
            self._backup_corrupted()
            return _StoreData(
                version=CURRENT_VERSION, default_profile_id=None, profiles=[]
            )

        default_id = raw.get("default_profile_id")
        if default_id is not None and not isinstance(default_id, str):
            default_id = None

        return _StoreData(
            version=int(raw.get("version", CURRENT_VERSION)),
            default_profile_id=default_id,
            profiles=profiles,
        )

    def _backup_corrupted(self) -> None:
        if not self._path.exists():
            return
        backup = self._path.with_suffix(self._path.suffix + ".corrupt")
        try:
            os.replace(self._path, backup)
        except OSError:
            # Best effort — don't fail loading because we can't move a file.
            pass

    def _save(self) -> None:
        payload: dict[str, Any] = {
            "version": self._data.version,
            "default_profile_id": self._data.default_profile_id,
            "profiles": [self._profile_to_dict(p) for p in self._data.profiles],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self._path)

    @staticmethod
    def _profile_to_dict(p: Profile) -> dict[str, Any]:
        # Tokens go through DPAPI encryption on Windows; on other
        # platforms ``encrypt`` is a no-op so the value round-trips as
        # plaintext (good enough for tests and dev shells).
        token = secure_storage.encrypt(p.token) if p.token else p.token
        password = secure_storage.encrypt(p.password) if p.password else p.password
        return {
            "id": p.id,
            "name": p.name,
            "token": token,
            "password": password,
            "email": p.email,
            "created_at": p.created_at.isoformat(),
            "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
        }

    @staticmethod
    def _dict_to_profile(d: object) -> Profile:
        if not isinstance(d, dict):
            raise TypeError("profile entry must be a JSON object")
        last_used_raw = d.get("last_used_at")
        raw_token = d.get("token") if isinstance(d.get("token"), str) else None
        # ``decrypt`` returns the input unchanged when the value carries
        # no ``dpapi:v1:`` marker — that's how plaintext tokens written
        # by older versions of the app keep working. A genuine DPAPI
        # failure (corrupted blob, user account changed) returns "",
        # which we surface as ``None`` so the UI prompts a re-login.
        decrypted = secure_storage.decrypt(raw_token) if raw_token else ""
        token = decrypted if decrypted else None
        raw_password = d.get("password") if isinstance(d.get("password"), str) else None
        decrypted_pw = secure_storage.decrypt(raw_password) if raw_password else ""
        password = decrypted_pw if decrypted_pw else None
        return Profile(
            id=str(d["id"]),
            name=str(d["name"]),
            token=token,
            email=d.get("email") if isinstance(d.get("email"), str) else None,
            password=password,
            created_at=datetime.fromisoformat(str(d["created_at"])),
            last_used_at=(
                datetime.fromisoformat(str(last_used_raw)) if last_used_raw else None
            ),
        )
