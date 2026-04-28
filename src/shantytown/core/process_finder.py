"""Detect game processes running outside of our launch session.

When the app starts up, the user might already have games running —
either because they launched them via this app last session and then
closed our window, or because they launched the same game from the
official DMM client. We scan the OS process list for executables
that match configured game paths so cards can show "실행 중" on first
paint instead of waiting for the user to click and discover the
process is still up.

Pure logic + ``psutil`` only — no Qt — so it can be unit-tested with
``psutil.process_iter`` mocked.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import psutil


def _normalize(path: Path) -> str:
    """Return a comparable path string.

    Resolves symlinks where possible and applies ``os.path.normcase``
    so Windows comparisons (``C:\\Foo\\game.exe`` vs ``c:\\foo\\GAME.EXE``)
    succeed regardless of how the path was originally typed.
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def find_running_pids(exe_paths: Iterable[Path]) -> dict[Path, int]:
    """Map each input ``exe_path`` to the PID of a running process whose
    executable matches.

    Args:
        exe_paths: Game executables to look for. Paths without a
            running match are simply absent from the result.

    Returns:
        Dict keyed by the *original* input :class:`Path` → PID. At most
        one match per path (the first encountered process wins).
    """
    paths = list(exe_paths)
    if not paths:
        return {}
    targets: dict[str, Path] = {_normalize(p): p for p in paths}
    out: dict[Path, int] = {}
    for proc in psutil.process_iter(["exe", "pid"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        exe = info.get("exe") if isinstance(info, dict) else None
        if not exe:
            continue
        key = os.path.normcase(str(exe))
        target_path = targets.get(key)
        if target_path is not None and target_path not in out:
            try:
                out[target_path] = int(info["pid"])
            except (KeyError, TypeError, ValueError):
                continue
            if len(out) == len(targets):
                break
    return out


def is_pid_alive(pid: int) -> bool:
    """Whether the process with ``pid`` is still running.

    Treats zombies as not alive (they're effectively done from a
    user's perspective). Errors during inspection (permission,
    transient gone-away) also count as not alive.
    """
    try:
        proc = psutil.Process(pid)
        return bool(proc.is_running()) and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
