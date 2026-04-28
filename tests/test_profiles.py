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
