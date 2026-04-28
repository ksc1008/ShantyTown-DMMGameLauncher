"""Tests for core.process_finder.

We mock ``psutil.process_iter`` so the tests don't depend on a real
running process — predictable on any host. ``is_pid_alive`` is
exercised against a real subprocess we own so it actually flexes
``psutil.Process``.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock

from shantytown.core import process_finder


class _FakeProc:
    """Minimal ``psutil.Process`` stand-in for ``process_iter`` mocking."""

    def __init__(self, pid: int, exe: str | None) -> None:
        self.info = {"pid": pid, "exe": exe}


def test_no_inputs_returns_empty():
    assert process_finder.find_running_pids([]) == {}


def test_single_match(monkeypatch, tmp_path):
    target = tmp_path / "game.exe"
    target.write_bytes(b"")
    procs = [
        _FakeProc(101, str(target)),
        _FakeProc(102, "C:/other/thing.exe"),
    ]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([target])
    assert out == {target: 101}


def test_returns_first_match_only(monkeypatch, tmp_path):
    """If two processes share the exe path we report just one PID."""
    target = tmp_path / "g.exe"
    target.write_bytes(b"")
    procs = [
        _FakeProc(200, str(target)),
        _FakeProc(201, str(target)),
    ]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([target])
    assert out == {target: 200}


def test_case_insensitive_path_match(monkeypatch, tmp_path):
    """Windows paths can come back from psutil with different casing."""
    target = tmp_path / "Game.EXE"
    target.write_bytes(b"")
    # ``proc.info['exe']`` lowercased — should still match on Windows.
    procs = [_FakeProc(300, str(target).lower())]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([target])
    if sys.platform.startswith("win"):
        assert out == {target: 300}
    else:
        # POSIX file systems are case-sensitive — both behaviours OK.
        assert out in ({target: 300}, {})


def test_unmatched_paths_absent_from_result(monkeypatch, tmp_path):
    a = tmp_path / "a.exe"
    b = tmp_path / "b.exe"
    a.write_bytes(b"")
    b.write_bytes(b"")
    procs = [_FakeProc(400, str(a))]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([a, b])
    assert out == {a: 400}


def test_skips_processes_with_no_exe(monkeypatch, tmp_path):
    target = tmp_path / "g.exe"
    target.write_bytes(b"")
    procs = [
        _FakeProc(500, None),
        _FakeProc(501, ""),
        _FakeProc(502, str(target)),
    ]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([target])
    assert out == {target: 502}


def test_skips_inaccessible_processes(monkeypatch, tmp_path):
    """``NoSuchProcess`` / ``AccessDenied`` raised on .info access must
    not break the scan — psutil emits these for transient / privileged
    processes."""
    target = tmp_path / "g.exe"
    target.write_bytes(b"")

    bad = MagicMock()
    type(bad).info = property(
        lambda _self: (_ for _ in ()).throw(process_finder.psutil.NoSuchProcess(999))
    )
    procs = [bad, _FakeProc(600, str(target))]
    monkeypatch.setattr(process_finder.psutil, "process_iter", lambda _f: iter(procs))
    out = process_finder.find_running_pids([target])
    assert out == {target: 600}


# --- live psutil check ---


def test_is_pid_alive_for_running_process():
    """Spawn a python interpreter that sleeps; check liveness; tear down."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert process_finder.is_pid_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_is_pid_alive_for_dead_process():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    # PID may be reused but very unlikely within this micro-window.
    assert process_finder.is_pid_alive(proc.pid) is False
