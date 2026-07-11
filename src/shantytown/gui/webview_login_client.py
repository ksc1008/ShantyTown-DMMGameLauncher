"""IPC client that drives the separate ``__loginhelper`` webview process.

Mirrors ``WebviewLoginAgent``'s ``succeeded``/``failed`` interface so
``main_window`` stays agnostic — but instead of loading QtWebEngine in
the main process, it spawns the ``__loginhelper`` executable and talks
JSON lines over stdin/stdout. This keeps the heavy Chromium payload out
of the main app entirely.

The helper process is **kept warm across login attempts**: spawning a
fresh Chromium per attempt costs several seconds, so once started the
helper stays alive and later ``start()`` calls just write another
request down the same pipe. ``abort()`` cancels the in-flight login but
leaves the process running; ``shutdown()`` (called by the owner after a
successful game launch or on app exit) terminates it for good.

Each request carries a sequence ``id`` echoed back by the helper, so a
late response from an aborted attempt can never be mistaken for the
current one.

Failure reasons are stable codes (``helper_missing``, ``helper_exited``,
``helper_error``, ``timeout``) or the helper's own error string — the
owner maps them to user-facing text.

Robustness: if the helper is missing, ``start`` emits ``failed`` (it
never raises) and ``helper_command()`` returns ``None`` so the UI hides
the webview option and forces the browser flow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from shantytown.core.debug import is_debug, show_webview

_HELPER_STEM = "__loginhelper"
# Generous: a onefile helper's first launch unpacks its bundle + spins up
# Chromium, then the login itself (reCAPTCHA, redirects) takes a while.
_TIMEOUT_MS = 180_000
_VISIBLE_TIMEOUT_MS = 600_000
_CREATE_NO_WINDOW = 0x08000000  # Win32: no console window for the child


def _frozen_helper_path() -> Path:
    name = f"{_HELPER_STEM}.exe" if sys.platform == "win32" else _HELPER_STEM
    return Path(sys.executable).resolve().parent / name


def helper_command() -> list[str] | None:
    """Command to launch the webview helper, or ``None`` if unavailable.

    Frozen build: the ``__loginhelper`` exe sitting next to the main exe
    (``None`` if it wasn't shipped — browser-only install). Dev: run the
    helper module with the current interpreter, provided QtWebEngine is
    importable here.
    """
    if getattr(sys, "frozen", False):
        exe = _frozen_helper_path()
        return [str(exe)] if exe.is_file() else None
    import importlib.util

    if importlib.util.find_spec("PyQt6.QtWebEngineCore") is None:
        return None
    return [sys.executable, "-m", "shantytown.loginhelper"]


def _hide_console(proc: QProcess) -> None:
    """Suppress a console-window flash when spawning the console helper."""
    if sys.platform != "win32":
        return

    def _modify(args: object) -> None:
        args.flags |= _CREATE_NO_WINDOW  # type: ignore[attr-defined]

    # Not in the PyQt6 type stubs on every platform — access dynamically.
    modifier = getattr(proc, "setCreateProcessArgumentsModifier", None)
    if modifier is not None:
        modifier(_modify)


class WebviewLoginClient(QObject):
    """Drives webview logins via a warm, reusable helper process."""

    succeeded = pyqtSignal(str)  # oauth code
    failed = pyqtSignal(str)  # reason code / helper error string
    engineReady = pyqtSignal()  # helper reported the engine is up

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._done = True  # no request in flight
        self._req_id = 0
        self._buf = ""
        # Request written once the (cold) process reaches started.
        self._pending: bytes | None = None
        self._proc = QProcess(self)
        self._proc.started.connect(self._on_started)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._proc.finished.connect(self._on_finished)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

    # --- public ---

    def start(self, login_url: str, email: str, password: str) -> None:
        """Begin a login attempt, spawning the helper only if needed."""
        self._req_id += 1
        self._done = False
        request = (
            json.dumps(
                {
                    "id": self._req_id,
                    "login_url": login_url,
                    "email": email,
                    "password": password,
                    "debug": is_debug(),
                    "show_webview": show_webview(),
                }
            )
            + "\n"
        ).encode("utf-8")
        self._timeout.start(
            _VISIBLE_TIMEOUT_MS if show_webview() else _TIMEOUT_MS
        )
        if self._proc.state() == QProcess.ProcessState.Running:
            # Warm helper — reuse it, no spawn cost.
            self._proc.write(request)
            return
        self._pending = request
        if self._proc.state() == QProcess.ProcessState.Starting:
            return  # _on_started will flush _pending
        cmd = helper_command()
        if cmd is None:
            self._fail("helper_missing")
            return
        program, *args = cmd
        self._proc.setProgram(program)
        self._proc.setArguments(args)
        _hide_console(self._proc)
        self._buf = ""
        self._proc.start()

    def abort(self) -> None:
        """Cancel the in-flight login; the helper stays warm for reuse."""
        if self._done:
            return
        self._done = True
        self._timeout.stop()
        self._pending = None
        if self._proc.state() == QProcess.ProcessState.Running:
            self._proc.write(b'{"cmd": "abort"}\n')

    def shutdown(self) -> None:
        """Terminate the helper process for good (game launched / app exit)."""
        self._done = True
        self._timeout.stop()
        self._pending = None
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()

    # --- QProcess handlers ---

    def _on_started(self) -> None:
        if self._pending is not None:
            self._proc.write(self._pending)
            self._pending = None

    def _on_stdout(self) -> None:
        self._buf += self._proc.readAllStandardOutput().data().decode(
            "utf-8", errors="replace"
        )
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return  # ignore non-JSON chatter
        if not isinstance(msg, dict):
            return
        # Stale response from a replaced/aborted request — drop it.
        if "id" in msg and msg["id"] != self._req_id:
            return
        if self._done:
            return
        if msg.get("status") == "ready":
            self.engineReady.emit()
            return
        if "ok" in msg:
            if msg.get("ok"):
                self._succeed(str(msg.get("code", "")))
            else:
                self._fail(str(msg.get("error") or "login failed"))

    def _on_stderr(self) -> None:
        text = self._proc.readAllStandardError().data().decode(
            "utf-8", errors="replace"
        )
        # Forward the helper's diagnostics to our stderr under --debug.
        if text.strip() and (is_debug() or show_webview()) and sys.stderr:
            sys.stderr.write(text)

    def _on_proc_error(self, _error: QProcess.ProcessError) -> None:
        if not self._done:
            self._fail("helper_error")

    def _on_finished(
        self, _code: int, _status: QProcess.ExitStatus
    ) -> None:
        # Helper died mid-request → fail it. The next start() respawns.
        if not self._done:
            self._fail("helper_exited")

    def _on_timeout(self) -> None:
        if self._done:
            return
        # A hung helper is not worth keeping warm — kill it; the next
        # attempt starts a fresh one.
        self._proc.kill()
        self._fail("timeout")

    # --- terminal ---

    def _succeed(self, code: str) -> None:
        if not code:
            self._fail("redirect_without_code")
            return
        self._finish()
        self.succeeded.emit(code)

    def _fail(self, reason: str) -> None:
        self._finish()
        self.failed.emit(reason)

    def _finish(self) -> None:
        self._done = True
        self._timeout.stop()
