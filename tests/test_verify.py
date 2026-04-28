"""Tests for core.verify."""

from __future__ import annotations

import hashlib

from shantytown.core.models import FileEntry
from shantytown.core.verify import verify_files


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _by_path(results, local_path):
    for r in results:
        if r.file.local_path == local_path:
            return r
    raise AssertionError(f"no result for {local_path}")


def test_missing_file(tmp_path):
    entries = [FileEntry("a.txt", "/a.txt", _md5(b"hello"), 5)]
    results = verify_files(entries, tmp_path)
    assert len(results) == 1
    assert results[0].needs_download is True
    assert results[0].reason == "missing"


def test_size_mismatch(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"hello")
    entries = [FileEntry("a.txt", "/a.txt", _md5(b"hello"), 99)]
    results = verify_files(entries, tmp_path)
    assert results[0].reason == "size_mismatch"
    assert results[0].needs_download is True


def test_hash_mismatch(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"hello")
    # correct size, wrong expected hash
    entries = [FileEntry("a.txt", "/a.txt", _md5(b"world"), 5)]
    results = verify_files(entries, tmp_path)
    assert results[0].reason == "hash_mismatch"
    assert results[0].needs_download is True


def test_clean_file(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"hello")
    entries = [FileEntry("a.txt", "/a.txt", _md5(b"hello"), 5)]
    results = verify_files(entries, tmp_path)
    assert results[0].needs_download is False
    assert results[0].reason is None


def test_mixed_batch_and_progress(tmp_path):
    # two clean, two missing, one bad-hash
    (tmp_path / "ok1").write_bytes(b"a")
    (tmp_path / "ok2").write_bytes(b"bb")
    (tmp_path / "bad").write_bytes(b"x" * 3)
    entries = [
        FileEntry("ok1", "/ok1", _md5(b"a"), 1),
        FileEntry("ok2", "/ok2", _md5(b"bb"), 2),
        FileEntry("bad", "/bad", _md5(b"yyy"), 3),
        FileEntry("missing1", "/m1", _md5(b""), 0),
        FileEntry("missing2", "/m2", _md5(b""), 5),
    ]
    progress: list[tuple[int, int]] = []
    results = verify_files(
        entries, tmp_path, max_workers=3, progress_cb=lambda c, t: progress.append((c, t))
    )
    assert len(results) == 5
    assert _by_path(results, "ok1").needs_download is False
    assert _by_path(results, "ok2").needs_download is False
    assert _by_path(results, "bad").reason == "hash_mismatch"
    assert _by_path(results, "missing1").reason == "missing"
    assert _by_path(results, "missing2").reason == "missing"
    # progress_cb fires once per entry; final tick reports total
    assert len(progress) == 5
    assert progress[-1] == (5, 5)


def test_empty_input(tmp_path):
    assert verify_files([], tmp_path) == []
