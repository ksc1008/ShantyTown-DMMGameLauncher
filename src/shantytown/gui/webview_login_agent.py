"""Headless webview login agent (the ``webview`` login method).

Drives an off-screen Chromium (QtWebEngine) through DMM's real login
page so the credential POST is built *by the page itself* — including
the JS-generated ``recaptchaToken`` (reCAPTCHA Enterprise) and
``user_device`` fraud fingerprint. We only fill the email/password and
click the page's own submit button; we never reconstruct the POST. That
is what makes us indistinguishable from an ordinary Chrome incognito
session (requirement: don't get flagged as a bot).

Design notes:

- **No official launcher.** After a successful login DMM redirects to a
  ``dmmgameplayer5://...?code=`` custom-scheme URL. In a normal browser
  the OS would hand that to the official DMM launcher. QtWebEngine does
  not auto-launch external schemes, and we additionally cancel the
  navigation in ``acceptNavigationRequest`` and capture the ``code``
  ourselves — so the launcher never opens.
- **Invisible.** The ``QWebEngineView`` is never shown. Failures are
  reported via the ``failed`` signal with a console-loggable reason.
- **All DMM-DOM knowledge is isolated** to the selector constants and JS
  builders below plus ``core.login_parsing`` — a page change is a
  one-file edit (requirement: parsing must be tightly modularised).

QtWebEngine runs on the GUI thread only, so this agent is signal-driven
on the main thread rather than a ``QThread`` worker.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from shantytown.core import login_parsing
from shantytown.core.debug import is_debug, show_webview

# --- DMM login page DOM contract (requirement: keep all selectors here) ---
_LOGIN_ID_SELECTOR = "#login_id"
_PASSWORD_SELECTOR = "#password"
_SUBMIT_SELECTOR = "form[name='loginForm'] button[type='submit']"
_NEXT_DATA_SELECTOR = "#__NEXT_DATA__"

# The post-login redirect (HTTPS success URL and/or custom scheme) is
# recognised by ``login_parsing.is_login_redirect`` — the single place
# that knows DMM's redirect shape.

# Pose as an ordinary desktop Chrome (matches the incognito-Chrome path
# the user verified works without a proxy).
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Wait for deferred scripts (reCAPTCHA, fraud SDK) to initialise before we
# submit, and an overall ceiling after which we assume a challenge/2FA wall.
_READY_POLL_MS = 300
_READY_MAX_TRIES = 40  # ~12s
_OVERALL_TIMEOUT_MS = 60_000
# When the window is shown (--show-webview) the developer may need to clear
# an interactive challenge by hand, so give them much longer.
_VISIBLE_TIMEOUT_MS = 300_000


def _log(msg: str) -> None:
    """Console diagnostics, active under --debug or --show-webview."""
    if is_debug() or show_webview():
        print(f"[webview-login] {msg}", file=sys.stderr)


def ready_js() -> str:
    """JS returning True once the form + reCAPTCHA are ready to submit."""
    return (
        "(function(){"
        f"var id=document.querySelector({json.dumps(_LOGIN_ID_SELECTOR)});"
        f"var btn=document.querySelector({json.dumps(_SUBMIT_SELECTOR)});"
        "var rc=!!(window.grecaptcha&&(window.grecaptcha.enterprise||window.grecaptcha.execute));"
        "return !!id&&!!btn&&rc;})()"
    )


def fill_and_submit_js(email: str, password: str) -> str:
    """JS that fills the credentials (React-safe) and clicks submit.

    Returns ``'submitted'`` on success, or ``'no_fields'`` /
    ``'no_submit'`` if the expected elements are missing.
    """
    return (
        "(function(email,password){"
        "function setValue(el,val){"
        "var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value');"
        "if(d&&d.set){d.set.call(el,val);}else{el.value=val;}"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));}"
        f"var id=document.querySelector({json.dumps(_LOGIN_ID_SELECTOR)});"
        f"var pw=document.querySelector({json.dumps(_PASSWORD_SELECTOR)});"
        "if(!id||!pw)return 'no_fields';"
        "setValue(id,email);setValue(pw,password);"
        f"var btn=document.querySelector({json.dumps(_SUBMIT_SELECTOR)});"
        "if(!btn)return 'no_submit';"
        "btn.click();return 'submitted';"
        f"}})({json.dumps(email)},{json.dumps(password)})"
    )


def read_next_data_js() -> str:
    """JS returning the raw ``__NEXT_DATA__`` JSON text (or '')."""
    return (
        "(function(){"
        f"var el=document.querySelector({json.dumps(_NEXT_DATA_SELECTOR)});"
        "return el?el.textContent:'';})()"
    )


class _CapturePage(QWebEnginePage):
    """Cancels the post-login redirect navigation and reports its URL.

    The ``code`` rides in the redirect URL itself (HTTPS success URL or
    the custom scheme). We cancel that navigation so the page never
    loads — which also stops any hand-off to the official DMM launcher.

    ``on_redirect`` runs *inside* this WebEngine C++ callback, so it must
    stay trivial (just stash the URL + schedule work); doing the real
    success handling here crashes the browser process.
    """

    def __init__(
        self,
        profile: QWebEngineProfile,
        parent: QObject,
        on_redirect: Callable[[str], None],
    ) -> None:
        super().__init__(profile, parent)
        self._on_redirect = on_redirect

    def acceptNavigationRequest(
        self,
        url: QUrl,
        type_: QWebEnginePage.NavigationType,
        isMainFrame: bool,
    ) -> bool:
        target = url.toString()
        if login_parsing.is_login_redirect(target):
            self._on_redirect(target)
            return False  # don't load it → launcher never opens
        return super().acceptNavigationRequest(url, type_, isMainFrame)


class WebviewLoginAgent(QObject):
    """Automates one DMM login and yields the OAuth ``code``.

    Emits exactly one of ``succeeded(code)`` / ``failed(reason)``.
    """

    succeeded = pyqtSignal(str)  # oauth code
    failed = pyqtSignal(str)  # human-readable / loggable reason

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._email = ""
        self._password = ""
        self._done = False
        self._submitted = False
        self._ready_tries = 0
        self._pending_redirect: str | None = None

        # An unnamed profile is off-the-record (incognito-equivalent): no
        # persistent cookies/cache, matching the fresh-session browser flow.
        self._profile = QWebEngineProfile(self)
        self._profile.setHttpUserAgent(_CHROME_UA)
        self._view = QWebEngineView()  # never shown → headless
        self._page = _CapturePage(self._profile, self, self._capture_redirect)
        self._view.setPage(self._page)
        self._page.loadFinished.connect(self._on_load_finished)

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)
        self._ready_timer = QTimer(self)
        self._ready_timer.setInterval(_READY_POLL_MS)
        self._ready_timer.timeout.connect(self._poll_ready)

    # --- public ---

    def start(self, login_url: str, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._done = False
        self._submitted = False
        self._ready_tries = 0
        if show_webview():
            self._view.setWindowTitle("DMM 로그인 (디버그 · 웹뷰 표시)")
            self._view.resize(520, 720)
            self._view.show()
            self._timeout.start(_VISIBLE_TIMEOUT_MS)
        else:
            self._timeout.start(_OVERALL_TIMEOUT_MS)
        _log(f"loading login url: {login_url}")
        self._page.load(QUrl(login_url))

    # --- flow ---

    def _capture_redirect(self, url: str) -> None:
        """Runs inside acceptNavigationRequest — keep it trivial.

        Just stash the URL and hand off to the event loop; the real
        success handling (teardown, token API, closing the dialog) must
        not run inside the WebEngine navigation callback.
        """
        if self._done or self._pending_redirect is not None:
            return
        self._pending_redirect = url
        QTimer.singleShot(0, self._process_pending_redirect)

    def _process_pending_redirect(self) -> None:
        if self._done:
            return
        self._on_redirect_captured(self._pending_redirect or "")

    def _on_load_finished(self, ok: bool) -> None:
        # A cancelled redirect navigation can still fire loadFinished(ok=
        # False); ignore it while a capture is already pending so we don't
        # mis-report a successful login as a load failure.
        if self._done or self._pending_redirect is not None:
            return
        current = self._page.url().toString()
        _log(f"load finished ok={ok} url={current} submitted={self._submitted}")
        # Fallback: if the success redirect actually loaded (wasn't cancelled
        # in acceptNavigationRequest), grab the code from the final URL.
        if login_parsing.is_login_redirect(current):
            self._on_redirect_captured(current)
            return
        if not ok:
            self._fail("page_load_failed")
            return
        if not self._submitted:
            # First load = the login page. Wait for deferred scripts.
            self._ready_tries = 0
            self._ready_timer.start()
        else:
            # Post-submit render. If DMM reports an error we stop; otherwise
            # the success path arrives as the redirect URL (or timeout).
            self._page.runJavaScript(read_next_data_js(), self._on_next_data)

    def _poll_ready(self) -> None:
        if self._done:
            return
        self._ready_tries += 1
        self._page.runJavaScript(ready_js(), self._on_ready_result)

    def _on_ready_result(self, ready: object) -> None:
        if self._done or self._submitted:
            return
        if bool(ready):
            self._ready_timer.stop()
            self._submit()
        elif self._ready_tries >= _READY_MAX_TRIES:
            self._ready_timer.stop()
            _log("readiness not confirmed within budget — submitting anyway")
            self._submit()

    def _submit(self) -> None:
        self._submitted = True
        _log("filling credentials and clicking submit")
        self._page.runJavaScript(
            fill_and_submit_js(self._email, self._password),
            self._on_submit_result,
        )

    def _on_submit_result(self, result: object) -> None:
        if self._done:
            return
        _log(f"submit result: {result}")
        if result in ("no_fields", "no_submit"):
            self._fail(f"form_not_found:{result}")

    def _on_next_data(self, text: object) -> None:
        if self._done:
            return
        errors = login_parsing.login_error_messages(str(text or ""))
        if errors:
            _log(f"server reported login error: {errors}")
            self._fail("; ".join(errors))
        # No error → keep waiting for the scheme redirect or the timeout.

    def _on_redirect_captured(self, url: str) -> None:
        if self._done:
            return
        _log(f"captured login redirect: {url}")
        code = login_parsing.extract_code(url)
        if code:
            self._succeed(code)
        else:
            self._fail("redirect_without_code")

    def _on_timeout(self) -> None:
        if self._done:
            return
        # Most likely an interactive reCAPTCHA challenge or a 2FA / device
        # verification wall that a headless flow can't clear.
        _log(
            "timed out waiting for the redirect — likely a reCAPTCHA challenge "
            "or 2FA/device-verification wall (try --show-webview to watch)"
        )
        self._fail("timeout")

    # --- terminal ---

    def abort(self) -> None:
        """Stop the login (user cancelled) without emitting an outcome.

        Tears down the Chromium view too, so a shown ``--show-webview``
        window closes with the dialog.
        """
        if self._done:
            return
        _log("aborted by user")
        self._teardown()

    def _succeed(self, code: str) -> None:
        self._teardown()
        self.succeeded.emit(code)

    def _fail(self, reason: str) -> None:
        self._teardown()
        self.failed.emit(reason)

    def _teardown(self) -> None:
        self._done = True
        self._timeout.stop()
        self._ready_timer.stop()
        try:
            self._page.loadFinished.disconnect(self._on_load_finished)
        except TypeError:
            pass  # already disconnected
        # Stop any in-flight load and tear down the page/view on the next
        # loop turn (never synchronously inside a navigation callback).
        self._page.triggerAction(QWebEnginePage.WebAction.Stop)
        QTimer.singleShot(0, self._view.deleteLater)
