"""Tests for store.profiles."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from shantytown.store.profiles import Profile, ProfileStore, ProfileStoreError


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "profiles.json"


def test_empty_store_has_no_profiles_or_default(store_path):
    s = ProfileStore(store_path)
    assert s.list() == []
    assert s.get_default() is None


def test_create_returns_profile_and_persists(store_path):
    s = ProfileStore(store_path)
    p = s.create("alice", token="tok-1", email="alice@example.com")
    assert p.name == "alice"
    assert p.token == "tok-1"
    assert p.email == "alice@example.com"
    assert p.id  # uuid populated
    assert store_path.is_file()

    # Reload from disk — same record comes back
    s2 = ProfileStore(store_path)
    assert len(s2.list()) == 1
    fetched = s2.get(p.id)
    assert fetched is not None
    assert fetched.name == "alice"
    assert fetched.token == "tok-1"
    assert fetched.email == "alice@example.com"


def test_first_profile_becomes_default(store_path):
    s = ProfileStore(store_path)
    first = s.create("alice")
    assert s.get_default() is not None
    assert s.get_default().id == first.id


def test_second_profile_does_not_displace_default(store_path):
    s = ProfileStore(store_path)
    first = s.create("alice")
    second = s.create("bob")
    assert s.get_default().id == first.id
    assert second.id != first.id


def test_set_default_explicitly(store_path):
    s = ProfileStore(store_path)
    s.create("alice")
    b = s.create("bob")
    s.set_default(b.id)
    assert s.get_default().id == b.id
    # Persists across reload
    s2 = ProfileStore(store_path)
    assert s2.get_default().id == b.id


def test_set_default_unknown_raises(store_path):
    s = ProfileStore(store_path)
    s.create("alice")
    with pytest.raises(ProfileStoreError):
        s.set_default("not-a-real-id")


def test_update_replaces_profile(store_path):
    s = ProfileStore(store_path)
    p = s.create("alice")
    updated = Profile(
        id=p.id,
        name="alice-renamed",
        token="newtok",
        created_at=p.created_at,
        last_used_at=datetime.now(UTC),
        email="alice2@example.com",
    )
    s.update(updated)
    fetched = s.get(p.id)
    assert fetched.name == "alice-renamed"
    assert fetched.token == "newtok"
    assert fetched.email == "alice2@example.com"
    assert fetched.last_used_at is not None


def test_update_unknown_raises(store_path):
    s = ProfileStore(store_path)
    ghost = Profile(
        id="no-such-id",
        name="ghost",
        token=None,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(ProfileStoreError):
        s.update(ghost)


def test_delete_removes_and_persists(store_path):
    s = ProfileStore(store_path)
    a = s.create("alice")
    b = s.create("bob")
    s.delete(a.id)
    assert [p.id for p in s.list()] == [b.id]
    s2 = ProfileStore(store_path)
    assert [p.id for p in s2.list()] == [b.id]


def test_delete_default_promotes_next(store_path):
    s = ProfileStore(store_path)
    a = s.create("alice")  # default
    b = s.create("bob")
    s.delete(a.id)
    assert s.get_default().id == b.id


def test_delete_only_profile_clears_default(store_path):
    s = ProfileStore(store_path)
    a = s.create("alice")
    s.delete(a.id)
    assert s.get_default() is None
    assert s.list() == []


def test_delete_unknown_raises(store_path):
    s = ProfileStore(store_path)
    with pytest.raises(ProfileStoreError):
        s.delete("no-such-id")


def test_consecutive_saves_do_not_corrupt(store_path):
    s = ProfileStore(store_path)
    s.create("alice")
    s.create("bob")
    s.create("carol")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["profiles"]) == 3


def test_corrupt_json_is_backed_up_and_store_starts_fresh(store_path):
    store_path.write_text("{not valid json", encoding="utf-8")
    s = ProfileStore(store_path)
    assert s.list() == []
    backup = store_path.with_suffix(store_path.suffix + ".corrupt")
    assert backup.is_file()


def test_email_round_trips(store_path):
    s = ProfileStore(store_path)
    p = s.create("alice", email="x@y.z")
    s2 = ProfileStore(store_path)
    assert s2.get(p.id).email == "x@y.z"


def test_email_defaults_to_none(store_path):
    s = ProfileStore(store_path)
    p = s.create("alice")
    assert p.email is None
    s2 = ProfileStore(store_path)
    assert s2.get(p.id).email is None


def test_legacy_plaintext_token_loads_unchanged(store_path):
    """A profiles.json from before DPAPI integration has plaintext
    tokens. They must keep loading so users don't have to re-login
    after upgrading."""
    import json
    from datetime import UTC, datetime

    legacy = {
        "version": 1,
        "default_profile_id": "p1",
        "profiles": [
            {
                "id": "p1",
                "name": "alice",
                "token": "plain-old-token",
                "email": None,
                "created_at": datetime.now(UTC).isoformat(),
                "last_used_at": None,
            }
        ],
    }
    store_path.write_text(json.dumps(legacy), encoding="utf-8")
    s = ProfileStore(store_path)
    loaded = s.get("p1")
    assert loaded is not None
    assert loaded.token == "plain-old-token"


def test_token_encrypted_on_disk_when_dpapi_supported(store_path):
    """Round-trip is transparent — but the file on disk should NOT
    contain the plaintext token when DPAPI is available."""
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")
    import json

    s = ProfileStore(store_path)
    s.create("alice", token="super-secret-token-12345")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk = raw["profiles"][0]["token"]
    assert "super-secret-token-12345" not in on_disk
    assert on_disk.startswith("dpapi:v1:")
    # And it round-trips back through a fresh load.
    s2 = ProfileStore(store_path)
    assert s2.list()[0].token == "super-secret-token-12345"


def test_password_round_trips(store_path):
    """A saved webview-login password survives a store reload."""
    s = ProfileStore(store_path)
    p = s.create("alice", email="alice@example.com")
    s.update(
        Profile(
            id=p.id,
            name=p.name,
            token=p.token,
            created_at=p.created_at,
            last_used_at=p.last_used_at,
            email=p.email,
            password="hunter2",
        )
    )
    s2 = ProfileStore(store_path)
    loaded = s2.get(p.id)
    assert loaded is not None
    assert loaded.password == "hunter2"
    assert loaded.email == "alice@example.com"


def test_password_defaults_to_none(store_path):
    s = ProfileStore(store_path)
    p = s.create("alice")
    assert p.password is None
    assert ProfileStore(store_path).get(p.id).password is None


def test_password_encrypted_on_disk_when_dpapi_supported(store_path):
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")

    s = ProfileStore(store_path)
    p = s.create("alice")
    s.update(
        Profile(
            id=p.id,
            name=p.name,
            token=None,
            created_at=p.created_at,
            last_used_at=p.last_used_at,
            email=None,
            password="super-secret-pw-12345",
        )
    )
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk = raw["profiles"][0]["password"]
    assert "super-secret-pw-12345" not in on_disk
    assert on_disk.startswith("dpapi:v1:")
    assert ProfileStore(store_path).get(p.id).password == "super-secret-pw-12345"


def test_new_store_writes_version_2(store_path):
    s = ProfileStore(store_path)
    s.create("alice", token="tok")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["version"] == 2


def test_secret_is_double_encrypted_on_disk_when_dpapi_supported(store_path):
    """On Windows the on-disk token is DPAPI(AES(token)): DPAPI on the
    outside, and peeling it reveals the AES envelope — not the token."""
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")
    from shantytown.core import secure_storage

    s = ProfileStore(store_path)
    s.create("alice", token="double-wrapped-secret-123")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk = raw["profiles"][0]["token"]
    assert on_disk.startswith("dpapi:v1:")
    assert "double-wrapped-secret-123" not in on_disk
    # Peel only the DPAPI layer → still AES ciphertext, not the secret.
    inner = secure_storage.decrypt(on_disk)
    assert inner.startswith(secure_storage.AES_PREFIX)
    assert "double-wrapped-secret-123" not in inner
    # Full round-trip still works.
    assert ProfileStore(store_path).get(s.list()[0].id).token == (
        "double-wrapped-secret-123"
    )


def test_migrates_v1_dpapi_only_to_v2_double_on_open(store_path):
    """A v1 file whose token is DPAPI-only (no AES) is re-encrypted to
    the v2 double layer on open, without a re-login."""
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")
    from shantytown.core import secure_storage

    # Hand-build a v1 file: DPAPI-encrypted token, version 1, no AES.
    v1_token = secure_storage.encrypt("legacy-v1-token")
    assert v1_token.startswith("dpapi:v1:")
    legacy = {
        "version": 1,
        "default_profile_id": "p1",
        "profiles": [
            {
                "id": "p1",
                "name": "alice",
                "token": v1_token,
                "email": None,
                "created_at": datetime.now(UTC).isoformat(),
                "last_used_at": None,
            }
        ],
    }
    store_path.write_text(json.dumps(legacy), encoding="utf-8")

    # Opening migrates: token decrypts in memory, file becomes v2 double.
    s = ProfileStore(store_path)
    assert s.get("p1").token == "legacy-v1-token"

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2
    migrated = on_disk["profiles"][0]["token"]
    assert migrated.startswith("dpapi:v1:")
    # Now double-wrapped: peeling DPAPI reveals the AES envelope.
    assert secure_storage.decrypt(migrated).startswith(secure_storage.AES_PREFIX)


def test_migration_keyed_to_id_wrong_id_cannot_decrypt(store_path):
    """The AES key is the profile id: a secret encrypted under one
    profile's id is unreadable if moved under a different id."""
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")
    from shantytown.core import secure_storage

    s = ProfileStore(store_path)
    p = s.create("alice", token="id-bound-secret")
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    stored_token = raw["profiles"][0]["token"]
    # Correct id decrypts; a different id does not.
    assert secure_storage.decrypt_secret(stored_token, p.id) == "id-bound-secret"
    assert secure_storage.decrypt_secret(stored_token, "some-other-id") == ""


def test_auto_migrates_legacy_plaintext_on_open(store_path):
    """A pre-DPAPI profiles.json with plaintext tokens gets re-saved
    in encrypted form the first time it's loaded, without requiring
    any user action."""
    import sys

    if sys.platform != "win32":
        pytest.skip("DPAPI only on Windows")
    import json
    from datetime import UTC, datetime

    legacy = {
        "version": 1,
        "default_profile_id": "p1",
        "profiles": [
            {
                "id": "p1",
                "name": "alice",
                "token": "legacy-plaintext-12345",
                "email": None,
                "created_at": datetime.now(UTC).isoformat(),
                "last_used_at": None,
            }
        ],
    }
    store_path.write_text(json.dumps(legacy), encoding="utf-8")

    # Just opening the store should rewrite the file in encrypted form.
    s = ProfileStore(store_path)
    assert s.list()[0].token == "legacy-plaintext-12345"  # decrypted in memory

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk_token = on_disk["profiles"][0]["token"]
    assert "legacy-plaintext-12345" not in on_disk_token
    assert on_disk_token.startswith("dpapi:v1:")
