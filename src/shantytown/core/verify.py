"""Parallel MD5 verification of an installed game directory.

This is the equivalent of ``Test-GameFiles`` in the reference PS1: walk
the file list, compare each entry against the on-disk file, and return
the ones that need re-downloading. Hashing is done on a thread pool
because we're I/O-bound and MD5 is fast.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .models import FileEntry

_HASH_CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class VerificationResult:
    """One entry's verdict.

    ``reason`` is one of ``'missing'``, ``'size_mismatch'``,
    ``'hash_mismatch'``, ``'unreadable'``, or ``None`` (file is fine).
    """

    file: FileEntry
    needs_download: bool
    reason: str | None


def _verify_one(entry: FileEntry, base_dir: Path) -> VerificationResult:
    path = base_dir / entry.local_path
    if not path.exists():
        return VerificationResult(entry, True, "missing")
    try:
        actual_size = path.stat().st_size
    except OSError:
        return VerificationResult(entry, True, "unreadable")
    if actual_size != entry.size:
        return VerificationResult(entry, True, "size_mismatch")

    md5 = hashlib.md5()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(_HASH_CHUNK)
                if not chunk:
                    break
                md5.update(chunk)
    except OSError:
        return VerificationResult(entry, True, "unreadable")

    if md5.hexdigest().lower() != entry.hash.lower():
        return VerificationResult(entry, True, "hash_mismatch")
    return VerificationResult(entry, False, None)


def verify_files(
    entries: list[FileEntry],
    base_dir: Path,
    max_workers: int = 8,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[VerificationResult]:
    """Verify all ``entries`` against files under ``base_dir``.

    Args:
        entries: File-list entries from the API.
        base_dir: Game install directory; entries are joined to this.
        max_workers: Worker thread count. The PS1 default is 8.
        progress_cb: Called as ``(completed, total)`` once per finished
            entry. Order is *not* guaranteed to match input order.

    Returns:
        One ``VerificationResult`` per entry. Order is non-deterministic.
    """
    total = len(entries)
    if total == 0:
        return []
    results: list[VerificationResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_verify_one, entry, base_dir) for entry in entries]
        for completed_count, fut in enumerate(as_completed(futures), start=1):
            results.append(fut.result())
            if progress_cb is not None:
                progress_cb(completed_count, total)
    return results
