"""In-app credential login form (the ``webview`` login method).

When the global login method is ``webview`` (set from the profile
manager, today behind ``--debug``), a profile that needs to log in gets
this form instead of the external-browser + clipboard flow. The user
types their DMM email and password once; both are saved to the profile
— encrypted at rest via DPAPI, the same envelope used for the access
token — so future logins can reuse them.

**Scope (current sprint):** this builds the *form* and its credential
persistence only. The webview automation that actually consumes these
credentials to mint a token lands in a later sprint. Pressing the login
button here persists nothing new and emits ``login_requested``; the
caller is expected to wire the automation onto that signal.

Interaction model (matches the agreed mock):

    ┌───────────────────────────────┐
    │                        [수정] │
    │ 이메일   someemail@gmail.com  │
    │ 비밀번호 ************         │
    │                               │
    │        [로그인]   [취소]      │
    └───────────────────────────────┘

- **View mode**: both fields are read-only; the bottom button reads
  "로그인" — stored credentials are ready to use. The top-right toggle
  shows a green "수정".
- **Edit mode**: fields are editable; the bottom button turns green and
  reads "완료" (commit + save). The top-right toggle turns into a
  default-colored "취소" that *cancels* the edit (reverts fields to the
  saved values) and returns to view mode.
- A profile with **no saved credentials** opens directly in edit mode
  with the top-right toggle hidden — there is no saved state to revert
  to, so the only exits are "완료" (save) or "취소" (close the dialog).
"""

from __future__ import annotations

import html
from dataclasses import replace

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.i18n import t
from shantytown.store.profiles import Profile, ProfileStore

from .icons import make_icon

_PRIMARY_BUTTON = (
    "QPushButton { background-color: #4a73c2; color: white; border: none; "
    "border-radius: 4px; padding: 6px 18px; font-weight: 500; min-height: 18px; }"
    "QPushButton:hover:!disabled { background-color: #3a5fa2; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
)
# Green — the "완료" (commit edit) action, matching the done/success green
# used for the login-dialog step badges.
_DONE_BUTTON = (
    "QPushButton { background-color: #10b981; color: white; border: none; "
    "border-radius: 4px; padding: 6px 18px; font-weight: 500; min-height: 18px; }"
    "QPushButton:hover:!disabled { background-color: #0e9f6e; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
)
_NEUTRAL_BUTTON = (
    "QPushButton { background-color: palette(button); color: palette(button-text); "
    "border: 1px solid palette(mid); border-radius: 4px; padding: 6px 14px; "
    "font-weight: 500; min-height: 18px; }"
    "QPushButton:hover:!disabled { background-color: palette(midlight); }"
)
# Read-only multi-line field holding DMM's verbatim (site) message —
# selectable so it can be copied, but visually distinct from an editable
# input.
_SITE_MESSAGE_FIELD = (
    "QTextEdit { background-color: palette(base); color: palette(text); "
    "border: 1px solid palette(mid); border-radius: 4px; padding: 4px 6px; }"
)


class WebLoginDialog(QDialog):
    """Credential form for the webview login method.

    Emits ``login_requested(email, password)`` when the user confirms a
    login with valid stored credentials.
    """

    login_requested = pyqtSignal(str, str)  # (email, password)

    # The site-message field grows with its content up to this height (px);
    # past it the field keeps this height and shows its own scrollbar.
    _SITE_MESSAGE_MAX_H = 120

    def __init__(
        self,
        profile: Profile,
        store: ProfileStore,
        parent: QWidget | None = None,
        *,
        auto_login: bool = False,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._store = store
        self._edit_mode = False
        # Whether the profile currently holds a saved email+password. Drives
        # the initial mode and the top-right toggle's visibility.
        self._has_saved = bool(profile.email) and bool(profile.password)
        self._auto_login = auto_login
        self._build_ui()
        self._load_credentials()
        # Auto-login: with saved credentials, start the login immediately so
        # the user never has to click the button. Deferred to the event loop
        # so it fires once the modal dialog is up (and can still be pre-empted
        # if the user jumps straight into editing).
        if self._auto_login and self._has_saved:
            QTimer.singleShot(0, self._auto_submit_login)

    # --- UI ---

    def _build_ui(self) -> None:
        self.setWindowTitle(t("weblogin.title"))
        self.setModal(True)
        # Width fixed; height floats from a compact baseline upward so a
        # multi-line failure message can expand the dialog (capped by the
        # message field's own max height + scrollbar — see _refit).
        self.setFixedWidth(400)
        self.setMinimumHeight(260)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        # Top row: heading left, edit toggle right.
        top = QHBoxLayout()
        top.addWidget(QLabel(f"<b>{t('weblogin.heading')}</b>"))
        top.addStretch(1)
        self._edit_toggle = QPushButton(t("weblogin.edit_button"))
        self._edit_toggle.setStyleSheet(_DONE_BUTTON)
        self._edit_toggle.clicked.connect(self._on_edit_toggle_clicked)
        top.addWidget(self._edit_toggle)
        root.addLayout(top)

        # Credential fields.
        form = QFormLayout()
        form.setSpacing(10)
        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText(t("weblogin.email_placeholder"))
        self._email_input.textChanged.connect(self._sync_primary_enabled)
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText(t("weblogin.password_placeholder"))
        self._password_input.textChanged.connect(self._sync_primary_enabled)
        # Password reveal toggle (eye icon on the trailing edge), the usual
        # web convention. Only offered in view mode — while editing, the
        # password stays masked (see _apply_mode).
        self._password_revealed = False
        self._icon_color = self.palette().color(
            QPalette.ColorRole.PlaceholderText
        ).name()
        reveal = self._password_input.addAction(
            make_icon("eye", 16, self._icon_color),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        assert reveal is not None  # addAction always returns the QAction
        self._reveal_action = reveal
        self._reveal_action.setToolTip(t("weblogin.reveal_password"))
        self._reveal_action.triggered.connect(self._toggle_password_reveal)
        form.addRow(t("weblogin.email_label"), self._email_input)
        form.addRow(t("weblogin.password_label"), self._password_input)
        root.addLayout(form)

        # Progress / status line — hidden until a login is in flight. Reused
        # to show a failure reason (in red) if the agent reports one. Kept
        # directly under the form (with the stretch moved below) so a
        # failure message sits close to the inputs rather than far beneath.
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        # DMM's raw site message (often Japanese, occasionally long).
        # Read-only but selectable so the user can copy the original text;
        # the "[Message]" prefix rides inline. Multi-line with word wrap: it
        # grows with its content up to a cap, then scrolls (see _refit).
        self._site_message_field = QTextEdit()
        self._site_message_field.setReadOnly(True)
        self._site_message_field.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._site_message_field.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._site_message_field.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._site_message_field.setStyleSheet(_SITE_MESSAGE_FIELD)
        self._site_message_field.setVisible(False)
        root.addWidget(self._site_message_field)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        root.addWidget(self._progress_bar)

        root.addStretch(1)

        # Bottom row: primary (login / done) + cancel.
        actions = QHBoxLayout()
        actions.addStretch(1)
        self._primary_btn = QPushButton()
        self._primary_btn.clicked.connect(self._on_primary_clicked)
        self._cancel_btn = QPushButton(t("weblogin.cancel_button"))
        self._cancel_btn.setStyleSheet(_NEUTRAL_BUTTON)
        self._cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self._primary_btn)
        actions.addWidget(self._cancel_btn)
        actions.addStretch(1)
        root.addLayout(actions)

    # --- state ---

    def _load_credentials(self) -> None:
        """Fill fields from the profile and pick the initial mode.

        Both credentials present → view mode (ready to log in). Anything
        missing → edit mode so the user is prompted to enter them.
        """
        self._load_fields_from_profile()
        self._edit_mode = not self._has_saved
        self._apply_mode()

    def _load_fields_from_profile(self) -> None:
        self._email_input.setText(self._profile.email or "")
        self._password_input.setText(self._profile.password or "")

    def _apply_mode(self) -> None:
        """Sync every widget to ``_edit_mode`` / ``_has_saved``."""
        edit = self._edit_mode
        self._email_input.setReadOnly(not edit)
        self._password_input.setReadOnly(not edit)

        # Password reveal: available only in view mode. While editing, the
        # password is always masked and the reveal control is hidden.
        if edit:
            self._set_password_revealed(False)
        self._reveal_action.setVisible(not edit)

        # Top-right toggle: only meaningful when there is a saved state to
        # revert to. Hidden entirely while entering first-time credentials.
        # View mode: green "수정" (enter edit); edit mode: default-colored
        # "취소" (revert the pending edit).
        self._edit_toggle.setVisible(self._has_saved)
        if edit:
            self._edit_toggle.setText(t("weblogin.cancel_button"))
            self._edit_toggle.setStyleSheet(_NEUTRAL_BUTTON)
        else:
            self._edit_toggle.setText(t("weblogin.edit_button"))
            self._edit_toggle.setStyleSheet(_DONE_BUTTON)

        # Bottom primary button morphs between login (blue) and done (green).
        if edit:
            self._primary_btn.setText(t("weblogin.done_button"))
            self._primary_btn.setStyleSheet(_DONE_BUTTON)
            self._email_input.setFocus()
        else:
            self._primary_btn.setText(t("weblogin.login_button"))
            self._primary_btn.setStyleSheet(_PRIMARY_BUTTON)
        self._sync_primary_enabled()

    def _sync_primary_enabled(self) -> None:
        """Both login and done require both fields to be non-empty."""
        both = bool(self._email_input.text().strip()) and bool(
            self._password_input.text().strip()
        )
        self._primary_btn.setEnabled(both)

    def _toggle_password_reveal(self) -> None:
        self._set_password_revealed(not self._password_revealed)

    def _set_password_revealed(self, revealed: bool) -> None:
        self._password_revealed = revealed
        self._password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if revealed else QLineEdit.EchoMode.Password
        )
        # Masked → eye ("show"); revealed → eye-off ("hide").
        self._reveal_action.setIcon(
            make_icon("eye_off" if revealed else "eye", 16, self._icon_color)
        )

    # --- actions ---

    def _on_edit_toggle_clicked(self) -> None:
        if self._edit_mode:
            # "취소" — leaving edit mode via the toggle discards the edit.
            self._load_fields_from_profile()
            self._edit_mode = False
        else:
            # "수정" — enter edit mode.
            self._edit_mode = True
        self._apply_mode()

    def _on_primary_clicked(self) -> None:
        if self._edit_mode:
            self._complete_edit()
        else:
            self._on_login()

    def _complete_edit(self) -> None:
        """Validate + persist the entered credentials, then return to view."""
        email = self._email_input.text().strip()
        password = self._password_input.text()
        if not email or not password:
            QMessageBox.warning(
                self,
                t("weblogin.empty.title"),
                t("weblogin.empty.body"),
            )
            return
        self._save_credentials(email, password)
        self._has_saved = True
        self._edit_mode = False
        self._apply_mode()

    def _save_credentials(self, email: str, password: str) -> None:
        """Persist the entered credentials to the profile (encrypted)."""
        self._profile = replace(self._profile, email=email, password=password)
        self._store.update(self._profile)

    def _on_login(self) -> None:
        email = self._email_input.text().strip()
        password = self._password_input.text()
        if not email or not password:
            return
        # Keep the dialog open and turn it into a progress view; the owner
        # drives the login agent and calls accept()/show_error() on the
        # outcome.
        self.enter_progress()
        self.login_requested.emit(email, password)

    def _auto_submit_login(self) -> None:
        """Fire the login automatically (auto-login with saved credentials).

        Guarded so it's a no-op if the user has meanwhile entered edit mode
        or a login is already running — auto-login should save a click, not
        override what the user is doing or loop after a failure.
        """
        if self._edit_mode or self._progress_bar.isVisible():
            return
        if self._email_input.text().strip() and self._password_input.text():
            self._on_login()

    # --- progress / outcome (driven by the owner) ---

    def enter_progress(self) -> None:
        """Switch the dialog into an in-flight state.

        Starts on the "웹뷰 로드중" (loading the QtWebEngine engine) phase —
        the heavy part on the first login. The owner flips the message to
        the sign-in phase via :meth:`set_progress_status` once the engine
        is ready.
        """
        self._status_label.setStyleSheet("")
        self._status_label.setText(t("weblogin.loading_engine"))
        self._status_label.setVisible(True)
        # Clear any prior failure's site message before a fresh attempt.
        self._site_message_field.setVisible(False)
        self._refit()
        self._progress_bar.setVisible(True)
        self._edit_toggle.setEnabled(False)
        self._email_input.setEnabled(False)
        self._password_input.setEnabled(False)
        self._primary_btn.setEnabled(False)
        # Cancel stays enabled so the user can abort an in-flight login
        # (rejecting the dialog stops the agent — see main_window).
        self._cancel_btn.setEnabled(True)

    def set_progress_status(self, text: str) -> None:
        """Update the in-progress status line (e.g. engine → sign-in)."""
        self._status_label.setText(text)

    def _resize_site_message(self) -> None:
        """Size the message field to its content, capped then scrolling.

        Short messages stay compact; longer ones grow the field (and, via
        :meth:`_refit`, the dialog) up to ``_SITE_MESSAGE_MAX_H`` — beyond
        that the field keeps that height and its vertical scrollbar shows.
        """
        if not self._site_message_field.isVisible():
            return
        field = self._site_message_field
        doc = field.document()
        viewport = field.viewport()
        if doc is None or viewport is None:
            return
        width = viewport.width()
        if width <= 0:  # not laid out yet — estimate from the fixed width
            width = 360
        doc.setTextWidth(width)
        # Document height + the frame's top/bottom border so no clipping.
        needed = int(doc.size().height()) + 2 * field.frameWidth() + 2
        field.setFixedHeight(max(32, min(needed, self._SITE_MESSAGE_MAX_H)))

    def _refit(self) -> None:
        """Re-size the message field, then the dialog, to fit the content.

        Runs once now and again after the event loop lays widgets out (the
        field's real width is only known then), so the height is correct
        whether or not the dialog is already shown.
        """
        self._resize_site_message()
        self.adjustSize()  # grow/shrink within [minimumHeight, sizeHint]
        QTimer.singleShot(0, self._refit_deferred)

    def _refit_deferred(self) -> None:
        self._resize_site_message()
        self.adjustSize()

    def show_error(
        self, message: str | None = None, *, site_message: str | None = None
    ) -> None:
        """Leave the progress state and surface a failure for retry.

        Rendered as a red "로그인 실패" headline. ``message`` is our own
        localised explanation (used for known failure kinds). ``site_message``
        is DMM's raw, verbatim text (often Japanese) — shown in a read-only
        but selectable "[Message]" field so the user can read/copy the
        original instead of being startled by foreign text in the body.
        """
        self._progress_bar.setVisible(False)
        self._status_label.setStyleSheet("color: #dc2626;")
        title = f"<b>{t('weblogin.failed_title')}</b>"
        if message:
            title = f"{title}<br>{html.escape(message)}"
        self._status_label.setText(title)
        self._status_label.setVisible(True)
        if site_message:
            prefix = t("weblogin.site_message_prefix")
            self._site_message_field.setPlainText(f"{prefix} {site_message}")
            self._site_message_field.moveCursor(QTextCursor.MoveOperation.Start)
            self._site_message_field.setVisible(True)
        else:
            self._site_message_field.setVisible(False)
        self._refit()
        self._cancel_btn.setEnabled(True)
        self._edit_toggle.setEnabled(True)
        self._email_input.setEnabled(True)
        self._password_input.setEnabled(True)
        # Restore field read-only / button state for the current mode so the
        # user can retry (or edit credentials and retry).
        self._apply_mode()
