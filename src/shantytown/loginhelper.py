"""Standalone webview login helper (built as the ``_loginhelper`` exe).

Built as a SEPARATE PyInstaller executable so the heavy QtWebEngine
(~127 MB Chromium) payload stays OUT of the main app — keeping the main
exe's startup fast. The main app spawns this helper on the first webview
login and talks to it over stdin/stdout (see ``gui.webview_login_client``).

The helper is a **long-lived session**: it keeps running after a login
finishes so subsequent attempts reuse the already-initialised QtWebEngine
(spawning a fresh Chromium per attempt is far too slow). The main app
terminates it after a successful game launch or on its own exit; the
helper also quits by itself when stdin closes (parent gone).

Protocol — one JSON object per line, any number of requests per session:

- in  (stdin):  ``{"id", "login_url", "email", "password", "debug"?, "show_webview"?}``
                start a login (aborts any in-flight one first)
- in  (stdin):  ``{"cmd": "abort"}``                abort the in-flight login
- out (stdout): ``{"status": "ready", "id"}``       engine up, logging in
                ``{"ok": true, "code": "...", "id"}``   success
                ``{"ok": false, "error": "...", "id"}`` failure

Exactly one terminal (``ok``) line is emitted per login request (none if
it was aborted); the echoed ``id`` lets the client drop stale responses.
Diagnostics go to stderr (forwarded to the main app under ``--debug``).
This module must never be imported by the main app — the agent factory
is what pulls in QtWebEngine.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Callable
from typing import IO, Any

from PyQt6.QtCore import QObject, pyqtSignal


def _reconfigure_stdio() -> None:
    """Force the stdio protocol channel to UTF-8.

    The client writes/reads UTF-8; the child's default stream encoding is
    the console code page (e.g. cp949 on Korean Windows), which cannot
    encode DMM's Japanese error messages. Left as-is, emitting such a
    message raises ``UnicodeEncodeError`` and the terminal line is lost —
    the client then never sees an outcome and hangs. ``_emit`` also
    ASCII-escapes as a fallback, but fixing the channel keeps the pipe
    clean end to end.
    """
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _emit(payload: dict[str, Any]) -> None:
    out = sys.stdout
    if out is None:  # console handle missing — nothing we can do
        return
    try:
        out.write(json.dumps(payload, ensure_ascii=False) + "\n")
        out.flush()
    except UnicodeEncodeError:
        # stdout isn't UTF-8 (legacy console code page) and the payload
        # has non-ASCII (a Japanese/Korean error message). Re-encode as
        # ASCII-escaped JSON so the line still gets through — dropping it
        # would leave the client waiting on an outcome that never comes.
        # ``UnicodeEncodeError`` subclasses ``ValueError``, so this clause
        # must precede the generic one below.
        try:
            out.write(json.dumps(payload, ensure_ascii=True) + "\n")
            out.flush()
        except (OSError, ValueError):
            pass
    except (OSError, ValueError):
        pass


def _default_agent_factory() -> Any:  # noqa: ANN401 (avoids importing QtWebEngine here)
    # Import (and thereby load QtWebEngine) only here, in this dedicated
    # process — never in the main app.
    from shantytown.gui.webview_login_agent import WebviewLoginAgent

    return WebviewLoginAgent()


class LoginSession(QObject):
    """Dispatches protocol lines to login agents, one login at a time.

    Lives for the whole helper process; each login request gets a fresh
    ``WebviewLoginAgent`` (off-the-record session), but the QtWebEngine
    runtime stays warm between requests — that is the whole point of
    keeping the process alive.
    """

    def __init__(
        self,
        agent_factory: Callable[[], Any] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._agent_factory = agent_factory or _default_agent_factory
        self._agent: Any = None
        self._req_id: object = None

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            _emit({"ok": False, "error": "invalid_request"})
            return
        if not isinstance(req, dict):
            _emit({"ok": False, "error": "invalid_request"})
            return
        if req.get("cmd") == "abort":
            self._abort_current()
            return
        self._start_login(req)

    def _abort_current(self) -> None:
        if self._agent is None:
            return
        agent, self._agent = self._agent, None
        self._req_id = None
        agent.abort()  # emits no outcome — the client already moved on

    def _start_login(self, req: dict[str, Any]) -> None:
        self._abort_current()
        # Propagate the parent's diagnostic flags so is_debug() /
        # show_webview() (read by the agent) behave the same here.
        if req.get("debug"):
            os.environ["SHANTYTOWN_DEBUG"] = "1"
        if req.get("show_webview"):
            os.environ["SHANTYTOWN_SHOW_WEBVIEW"] = "1"
        req_id = req.get("id")
        agent = self._agent_factory()
        self._agent = agent
        self._req_id = req_id
        agent.succeeded.connect(
            lambda code, rid=req_id: self._finish(rid, {"ok": True, "code": code})
        )
        agent.failed.connect(
            lambda reason, rid=req_id: self._finish(rid, {"ok": False, "error": reason})
        )
        # The agent (and with it the QWebEngineView) is constructed by now,
        # so the slow engine bring-up is done — tell the parent it can
        # switch its status from "loading" to "signing in". On a warm
        # session this arrives near-instantly.
        _emit(self._with_id({"status": "ready"}, req_id))
        agent.start(
            str(req.get("login_url", "")),
            str(req.get("email", "")),
            str(req.get("password", "")),
        )

    def _finish(self, req_id: object, payload: dict[str, Any]) -> None:
        if req_id != self._req_id:
            return  # stale outcome from a replaced/aborted login
        self._agent = None
        self._req_id = None
        _emit(self._with_id(payload, req_id))

    @staticmethod
    def _with_id(payload: dict[str, Any], req_id: object) -> dict[str, Any]:
        if req_id is not None:
            payload["id"] = req_id
        return payload


class _StdinBridge(QObject):
    """Pumps stdin lines from a reader thread onto the Qt main thread.

    Reading stdin blocks, and QSocketNotifier is unreliable for pipes on
    Windows — so a daemon thread reads and re-emits via queued signals.
    EOF (parent closed the pipe / exited) ends the session.
    """

    lineReceived = pyqtSignal(str)
    closed = pyqtSignal()

    def start(self, stream: IO[str]) -> None:
        thread = threading.Thread(
            target=self._pump, args=(stream,), daemon=True
        )
        thread.start()

    def _pump(self, stream: IO[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                self.lineReceived.emit(line)
        except (OSError, ValueError):
            pass
        self.closed.emit()


def main(argv: list[str] | None = None) -> int:
    stdin = sys.stdin
    if stdin is None:
        return 2
    _reconfigure_stdio()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(
        argv if argv is not None else sys.argv
    )

    session = LoginSession()
    bridge = _StdinBridge()
    bridge.lineReceived.connect(session.handle_line)
    bridge.closed.connect(app.quit)
    bridge.start(stdin)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
