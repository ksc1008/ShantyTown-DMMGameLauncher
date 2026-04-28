"""Auto-detect a game's exe inside its install directory.

Pure logic — lives in ``core`` so it can be unit-tested without Qt.
"""

from __future__ import annotations

from pathlib import Path


def find_exe_candidate(
    install_dir: Path, candidates: tuple[str, ...]
) -> Path | None:
    """Return the first existing exe matching one of ``candidates``.

    Search is case-insensitive and recursive: top-level directory first
    (cheap), then ``rglob('*')`` so binaries inside ``Game_Data/`` etc.
    still get picked up. Returns ``None`` when no match exists or the
    install directory is missing / candidates list is empty.
    """
    if not install_dir.exists() or not candidates:
        return None
    wanted = {c.lower() for c in candidates}
    for child in install_dir.iterdir():
        if child.is_file() and child.name.lower() in wanted:
            return child
    for path in install_dir.rglob("*"):
        if path.is_file() and path.name.lower() in wanted:
            return path
    return None
