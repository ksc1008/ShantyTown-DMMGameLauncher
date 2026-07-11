"""External-browser login flow.

Why not QtWebEngine: the official DMM Game Player is a real Electron app,
and routing the login through an in-app web view trips fingerprinting
heuristics (UA string, missing browser-only globals, navigator quirks).
The reference PowerShell prototype already uses the system browser plus a
manual paste, so we mirror that — a proven, low-risk path.

The "elegant" twist is that we *don't* make the user paste. After the
user clicks the open button, we:

1. Open the DMM login page in their default browser.
2. Snapshot the clipboard so we don't trigger on whatever was already
   there.
3. Poll the clipboard every 500 ms. The first time it changes to a value
   that contains a ``code=`` query parameter, we capture it and stop.
4. As a fallback for environments that block clipboard reads, an
   "advanced" expander offers a paste box.

The dialog emits ``token_issued(token, email)`` once issuance succeeds.
The actual ``issue_token`` HTTP call runs on a one-shot ``QThread`` to
keep the UI responsive.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import (
    QObject,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QClipboard, QGuiApplication, QShowEvent
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.api import DmmApiClient, DmmApiError
from shantytown.core.i18n import t

# Re-exported for backwards compatibility: the canonical implementation now
# lives in core.login_parsing (Qt-free, shared with the webview login agent).
from shantytown.core.login_parsing import extract_code

POLL_INTERVAL_MS = 500
DEFAULT_TIMEOUT_MS = 5 * 60 * 1000  # 5 minutes

__all__ = ["LoginDialog", "extract_code"]

# Inline styling — kept in one place so future theme work has a single
# touch point. We use ``palette(...)`` references everywhere a background
# would otherwise clash with dark mode. Brand-colored badges (filled
# blue / green) keep solid backgrounds so the white digit reads on any
# system theme. Active body text deliberately has no color override so
# the system foreground (light or dark) wins.
_STEP_NUMBER_ACTIVE = (
    "background-color: #2563eb; color: white; border-radius: 11px; "
    "font-weight: bold; padding: 1px 0px; min-width: 22px; max-width: 22px; "
    "min-height: 22px; max-height: 22px; qproperty-alignment: AlignCenter;"
)
_STEP_NUMBER_DIM = (
    "background-color: transparent; color: palette(placeholder-text); "
    "border: 1.5px solid palette(mid); border-radius: 11px; "
    "font-weight: bold; padding: 1px 0px; min-width: 22px; max-width: 22px; "
    "min-height: 22px; max-height: 22px; qproperty-alignment: AlignCenter;"
)
_STEP_NUMBER_DONE = (
    "background-color: #10b981; color: white; border-radius: 11px; "
    "font-weight: bold; padding: 1px 0px; min-width: 22px; max-width: 22px; "
    "min-height: 22px; max-height: 22px; qproperty-alignment: AlignCenter;"
)
# Active body uses default palette color + bold for emphasis (no color override
# so dark mode shows light text and light mode shows dark text).
_TEXT_ACTIVE = "font-size: 13px; font-weight: 600;"
_TEXT_DIM = "color: palette(placeholder-text); font-size: 13px;"
_TEXT_DONE = "color: palette(placeholder-text); font-size: 13px;"
_FALLBACK_NOTE = "color: palette(placeholder-text); font-size: 11px;"
_PRIMARY_BUTTON = (
    "QPushButton { background-color: #2563eb; color: white; "
    "padding: 8px 14px; border: none; border-radius: 6px; font-weight: 600; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
    "QPushButton:hover:!disabled { background-color: #1d4ed8; }"
)


class _IssueTokenWorker(QObject):
    """Off-thread wrapper around ``DmmApiClient.issue_token``."""

    succeeded = pyqtSignal(str)  # access_token
    failed = pyqtSignal(str)  # human-readable error message

    def __init__(self, api: DmmApiClient, code: str) -> None:
        super().__init__()
        self._api = api
        self._code = code

    def run(self) -> None:
        try:
            token = self._api.issue_token(self._code)
        except DmmApiError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:
            self.failed.emit(f"unexpected error: {e}")
            return
        self.succeeded.emit(token)


class _Step(QFrame):
    """One numbered step row with circle badge + body text."""

    def __init__(self, number: int, body: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._badge = QLabel(str(number))
        self._badge.setMinimumSize(22, 22)
        self._badge.setStyleSheet(_STEP_NUMBER_DIM)
        layout.addWidget(self._badge, alignment=layout.alignment())
        self._body = QLabel(body)
        self._body.setWordWrap(True)
        self._body.setStyleSheet(_TEXT_DIM)
        layout.addWidget(self._body, stretch=1)

    def set_active(self) -> None:
        self._badge.setStyleSheet(_STEP_NUMBER_ACTIVE)
        self._body.setStyleSheet(_TEXT_ACTIVE)

    def set_dim(self) -> None:
        self._badge.setStyleSheet(_STEP_NUMBER_DIM)
        self._body.setStyleSheet(_TEXT_DIM)

    def set_done(self) -> None:
        self._badge.setText("✓")
        self._badge.setStyleSheet(_STEP_NUMBER_DONE)
        self._body.setStyleSheet(_TEXT_DONE)

    def set_body(self, text: str) -> None:
        self._body.setText(text)


class LoginDialog(QDialog):
    """Modal dialog that brokers the OAuth code → access token flow."""

    token_issued = pyqtSignal(str, object)  # (access_token, email or None)

    def __init__(
        self,
        api: DmmApiClient,
        parent: QWidget | None = None,
        *,
        clipboard_factory: Callable[[], QClipboard] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._login_url: str | None = None
        self._initial_clipboard: str | None = None
        self._clipboard_factory = clipboard_factory or QGuiApplication.clipboard
        self._timeout_ms = timeout_ms
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_clipboard)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._issue_thread: QThread | None = None
        self._issue_worker: _IssueTokenWorker | None = None
        self._build_ui()

    # --- UI ---

    def _build_ui(self) -> None:
        self.setWindowTitle(t("login.title"))
        self.setModal(True)
        self.setFixedSize(520, 380)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        header = QLabel(f"<h3 style='margin:0;'>{t('login.heading')}</h3>")
        root.addWidget(header)

        self._step1 = _Step(1, t("login.step1"))
        root.addWidget(self._step1)

        self._open_button = QPushButton(t("login.open_button"))
        self._open_button.setStyleSheet(_PRIMARY_BUTTON)
        self._open_button.setMinimumHeight(36)
        self._open_button.clicked.connect(self._on_open_clicked)
        self._open_button.setEnabled(False)
        button_row = QHBoxLayout()
        button_row.addSpacing(32)  # align under the step body
        button_row.addWidget(self._open_button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self._step2 = _Step(2, t("login.step2"))
        root.addWidget(self._step2)

        # The status line is reserved for transient messages
        # (URL preparing, timeout, errors, success).
        self._status = QLabel(t("login.preparing"))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(_TEXT_DIM)
        root.addWidget(self._status)

        # Manual paste fallback
        fallback_note = QLabel(t("login.fallback_note"))
        fallback_note.setWordWrap(True)
        fallback_note.setStyleSheet(_FALLBACK_NOTE)
        root.addWidget(fallback_note)

        paste_row = QHBoxLayout()
        self._paste_input = QLineEdit()
        self._paste_input.setPlaceholderText(t("login.paste_placeholder"))
        self._paste_input.returnPressed.connect(self._on_paste_submit)
        self._paste_button = QPushButton(t("login.submit"))
        self._paste_button.clicked.connect(self._on_paste_submit)
        paste_row.addWidget(self._paste_input)
        paste_row.addWidget(self._paste_button)
        root.addLayout(paste_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # Initial state: step 1 active, step 2 dim
        self._step1.set_active()
        self._step2.set_dim()

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._prepare_login_url)

    # --- flow ---

    def _prepare_login_url(self) -> None:
        try:
            self._login_url = self._api.get_login_url()
        except DmmApiError as e:
            self._status.setText(t("login.url_failed", error=str(e)))
            return
        self._status.setText("")
        self._open_button.setEnabled(True)

    def _on_open_clicked(self) -> None:
        if not self._login_url:
            return
        clip = self._clipboard_factory()
        self._initial_clipboard = clip.text() if clip is not None else ""
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self._login_url))
        self._open_button.setEnabled(False)
        self._step1.set_done()
        self._step2.set_active()
        self._status.setText(t("login.after_open"))
        self._status.setStyleSheet(_TEXT_DIM)
        self._poll_timer.start()
        self._timeout_timer.start(self._timeout_ms)

    def _poll_clipboard(self) -> None:
        clip = self._clipboard_factory()
        if clip is None:
            return
        text = clip.text()
        if text == self._initial_clipboard:
            return
        code = extract_code(text)
        if not code:
            return
        self._handle_code(code)

    def _on_paste_submit(self) -> None:
        code = extract_code(self._paste_input.text())
        if not code:
            QMessageBox.warning(
                self,
                t("login.no_code.title"),
                t("login.no_code.body"),
            )
            return
        self._handle_code(code)

    def _handle_code(self, code: str) -> None:
        self._poll_timer.stop()
        self._timeout_timer.stop()
        self._open_button.setEnabled(False)
        self._paste_input.setEnabled(False)
        self._paste_button.setEnabled(False)
        self._progress.setVisible(True)
        self._step2.set_done()
        self._status.setText(t("login.saving"))
        self._status.setStyleSheet(_TEXT_ACTIVE)

        self._issue_thread = QThread(self)
        self._issue_worker = _IssueTokenWorker(self._api, code)
        self._issue_worker.moveToThread(self._issue_thread)
        self._issue_thread.started.connect(self._issue_worker.run)
        self._issue_worker.succeeded.connect(self._on_issue_success)
        self._issue_worker.failed.connect(self._on_issue_failed)
        self._issue_worker.succeeded.connect(self._issue_thread.quit)
        self._issue_worker.failed.connect(self._issue_thread.quit)
        self._issue_thread.finished.connect(self._issue_worker.deleteLater)
        self._issue_thread.finished.connect(self._issue_thread.deleteLater)
        self._issue_thread.start()

    def _on_issue_success(self, token: str) -> None:
        self.token_issued.emit(token, None)
        self.accept()

    def _on_issue_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status.setText(t("login.failed", error=message))
        self._open_button.setEnabled(True)
        self._paste_input.setEnabled(True)
        self._paste_button.setEnabled(True)
        # Re-arm so the user can retry by re-copying.
        self._step2.set_active()
        self._poll_timer.start()
        self._timeout_timer.start(self._timeout_ms)

    def _on_timeout(self) -> None:
        self._poll_timer.stop()
        self._status.setText(t("login.timeout"))
        self._open_button.setEnabled(True)

    # --- cleanup ---

    def reject(self) -> None:
        self._poll_timer.stop()
        self._timeout_timer.stop()
        super().reject()
