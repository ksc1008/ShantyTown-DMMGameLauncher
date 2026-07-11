"""Modal progress dialog for the launch flow.

Displays whatever stage label the worker emits, plus a determinate
progress bar driven by ``(current, total)``. Cancel sends an
interruption request to the owning ``QThread`` — the worker checks
``isInterruptionRequested()`` between steps.

On failure, ``finish`` looks for a debug detail block in the error
message (everything after the first blank line) and reveals it in a
scrollable, read-only text view. This keeps short errors compact while
still letting users copy a full DMM launch response when running with
``--debug``.

When the failure is an expired/invalid token, the owner can call
:py:meth:`enable_logout` (before ``finish`` runs) to add a "log out"
action button to the error dialog so the user can re-authenticate
without hunting through the profile manager.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.i18n import t

# Muted red for the destructive logout action — mirrors the danger
# button in the profile dialog so the two read as the same affordance.
_DANGER_BUTTON = (
    "QPushButton { background-color: #c25555; color: white; border: none; "
    "padding: 6px 14px; border-radius: 4px; }"
    "QPushButton:hover:!disabled { background-color: #a44545; }"
)


class ProgressDialog(QDialog):
    """Reusable progress dialog. Connect a worker's ``progress`` signal
    to :py:meth:`set_progress` and ``finished`` to :py:meth:`finish`.
    """

    def __init__(
        self,
        title: str,
        thread: QThread,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = thread
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        # Lock the size during the launch flow. ``_show_detail`` re-sets
        # a larger fixed size when debug-mode errors expand the dialog
        # — both calls are valid because ``setFixedSize`` overrides
        # itself.
        self.setFixedSize(440, 140)

        self._root = QVBoxLayout(self)
        self._stage = QLabel(t("progress.preparing"))
        self._stage.setWordWrap(True)
        self._stage.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._root.addWidget(self._stage)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._root.addWidget(self._bar)

        self._detail_view: QPlainTextEdit | None = None
        # Set via ``enable_logout`` before ``finish`` runs; when present,
        # the failure branch adds a logout button that invokes it.
        self._logout_callback: Callable[[], None] | None = None

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._buttons.rejected.connect(self._on_cancel)
        self._root.addWidget(self._buttons)

    def enable_logout(self, callback: Callable[[], None]) -> None:
        """Offer a logout action on the error screen.

        Call this before :py:meth:`finish` (e.g. from the worker's
        ``auth_invalid`` signal). ``callback`` runs when the user clicks
        the button; the dialog closes itself afterwards.
        """
        self._logout_callback = callback

    def set_progress(self, message: str, current: int, total: int) -> None:
        """Slot for ``LaunchWorker.progress``."""
        self._stage.setText(message)
        if total <= 0:
            self._bar.setRange(0, 0)
        else:
            self._bar.setRange(0, total)
            self._bar.setValue(min(current, total))

    def finish(self, success: bool, message: str) -> None:
        """Slot for ``LaunchWorker.finished``."""
        if success:
            self.accept()
            return

        # Split a single ``summary\n\n<detail>`` payload — the worker
        # uses this convention to attach debug context.
        parts = message.split("\n\n", 1)
        summary = parts[0]
        detail = parts[1].rstrip() if len(parts) > 1 else ""

        self._stage.setText(t("progress.failed", message=summary))
        self._bar.setRange(0, 1)
        self._bar.setValue(0)

        if detail:
            self._show_detail(detail)

        # Swap Cancel for Close, optionally preceded by a logout action.
        self._buttons.clear()
        self._buttons.rejected.disconnect()
        if self._logout_callback is not None:
            logout_btn = self._buttons.addButton(
                t("progress.logout_button"),
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            if logout_btn is not None:
                logout_btn.setStyleSheet(_DANGER_BUTTON)
                logout_btn.clicked.connect(self._on_logout)
        self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)

    def _on_logout(self) -> None:
        """Run the logout callback, then close the dialog."""
        if self._logout_callback is not None:
            self._logout_callback()
        self.reject()

    def _show_detail(self, detail: str) -> None:
        if self._detail_view is None:
            self._detail_view = QPlainTextEdit()
            self._detail_view.setReadOnly(True)
            self._detail_view.setMinimumHeight(160)
            self._detail_view.setMaximumHeight(360)
            self._detail_view.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth
            )
            # Insert above the button row.
            self._root.insertWidget(self._root.count() - 1, self._detail_view)
        self._detail_view.setPlainText(detail)
        # Grow the dialog so the detail area has room. ``setFixedSize``
        # supersedes the earlier 440x140 lock — still non-resizable for
        # the user, just at a different size.
        self.setFixedSize(720, 420)

    def _on_cancel(self) -> None:
        self._stage.setText(t("progress.cancel_requested"))
        cancel_btn = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setEnabled(False)
        self._thread.requestInterruption()
