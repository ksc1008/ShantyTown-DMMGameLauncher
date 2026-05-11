"""Per-game settings dialog.

Triggered from the ⚙ button on each card. Owns:

- exe path (auto-detected on first setup, edited here)
- display name override (None → use bundled / product_id)
- desktop shortcut creation (Windows ``.lnk`` via PowerShell COM)

Lives in its own module so future per-game settings (force-verify,
custom launch args, …) have somewhere to land without spaghettifying
the card.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.i18n import t
from shantytown.core.models import InstalledGame
from shantytown.gui.spinner import Spinner
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.known_games import KnownGame


class _ShortcutWorker(QObject):
    """Off-main-thread wrapper around ``create_desktop_shortcut``.

    The ``powershell.exe`` subprocess startup + AV scan runs 1-3 s on
    a typical Windows box. Doing it inline freezes the dialog for that
    whole window, which reads as "the app crashed" to the user. Punt
    the call to a QThread and surface progress via signals.
    """

    finished = pyqtSignal(bool, str, str)  # (success, lnk_path, error_message)

    def __init__(
        self,
        name: str,
        product_id: str,
        icon_path: Path | None,
    ) -> None:
        super().__init__()
        self._name = name
        self._product_id = product_id
        self._icon_path = icon_path

    def run(self) -> None:
        # Lazy-import so the module's PowerShell-touching code is only
        # pulled in when the user actually triggers a shortcut create.
        from shantytown.core.shortcuts import (
            ShortcutError,
            create_desktop_shortcut,
        )

        try:
            lnk = create_desktop_shortcut(
                name=self._name,
                product_id=self._product_id,
                icon_path=self._icon_path,
            )
        except ShortcutError as e:
            self.finished.emit(False, "", str(e))
            return
        except Exception as e:
            # Belt-and-suspenders — anything escaping ShortcutError still
            # has to flip the UI back into a usable state.
            self.finished.emit(False, "", f"{type(e).__name__}: {e}")
            return
        self.finished.emit(True, str(lnk), "")


class GameSettingsDialog(QDialog):
    # Emitted when a shortcut creation completes successfully. Wired
    # by MainWindow to drive the top-screen slide-down toast — keeps
    # the dialog ignorant of how the success is surfaced (toast vs
    # status bar vs whatever else later).
    shortcut_created = pyqtSignal(str)

    def __init__(
        self,
        installed: InstalledGame,
        known: KnownGame | None,
        game_store: GameStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._installed = installed
        self._known = known
        self._game_store = game_store
        # Owns the in-flight shortcut worker so we can clean up if the
        # user closes the dialog mid-creation. ``None`` while idle.
        self._shortcut_thread: QThread | None = None
        self._shortcut_worker: _ShortcutWorker | None = None
        # Captured at creation start so the success message uses the
        # name as it was when the user clicked, not whatever they edited
        # while waiting.
        self._pending_shortcut_name: str = ""

        existing = game_store.get(installed.product_id)
        self._initial_exe: Path | None = (
            existing.exe_path if existing is not None else None
        )
        self._initial_display_name: str | None = (
            existing.display_name if existing is not None else None
        )

        # Default name = bundled known_games name OR product_id. Used as
        # placeholder text on the rename field and as the title fallback.
        self._default_name: str = (
            known.display_name if known is not None else installed.product_id
        )
        # The name actually shown in the title is the user override
        # when present, else the default.
        title_name = self._initial_display_name or self._default_name
        self.setWindowTitle(t("game_settings.title", name=title_name))
        self.setModal(True)
        self.setFixedSize(560, 320)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{title_name}</b>"))
        root.addWidget(
            QLabel(
                f"{t('game_settings.install_path')} "
                f"<code>{installed.install_path}</code>"
            )
        )

        # --- display name override ---
        root.addSpacing(6)
        root.addWidget(QLabel(t("game_settings.display_name_label")))
        self._name_input = QLineEdit()
        self._name_input.setText(self._initial_display_name or "")
        self._name_input.setPlaceholderText(
            t(
                "game_settings.display_name_placeholder",
                default=self._default_name,
            )
        )
        root.addWidget(self._name_input)

        # --- exe path ---
        root.addSpacing(6)
        root.addWidget(QLabel(t("game_settings.exe_label")))
        path_row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.setText(
            str(self._initial_exe) if self._initial_exe is not None else ""
        )
        path_row.addWidget(self._path_input, stretch=1)
        browse_btn = QPushButton(t("game_settings.browse"))
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        root.addLayout(path_row)

        # --- desktop shortcut ---
        root.addSpacing(8)
        shortcut_row = QHBoxLayout()
        self._shortcut_btn = QPushButton(t("game_settings.create_shortcut"))
        self._shortcut_btn.clicked.connect(self._on_create_shortcut)
        shortcut_row.addWidget(self._shortcut_btn)
        # Inline spinner — invisible until creation kicks off, matches
        # the "creating…" status text. Smaller footprint than a
        # progress bar and reads as a spinner across both themes.
        self._shortcut_spinner = Spinner(size=18)
        self._shortcut_spinner.setVisible(False)
        shortcut_row.addSpacing(6)
        shortcut_row.addWidget(self._shortcut_spinner)
        shortcut_row.addStretch(1)
        root.addLayout(shortcut_row)

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # --- handlers ---

    def _browse(self) -> None:
        start = (
            str(self._installed.install_path)
            if self._installed.install_path.exists()
            else str(Path.home())
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("game_settings.choose.title"),
            start,
            t("main.exe_filter"),
        )
        if path:
            self._path_input.setText(path)

    def _on_create_shortcut(self) -> None:
        # Re-entrancy guard — disabled button should make this
        # impossible, but keep it tight in case of rapid double-click
        # before the disable lands.
        if self._shortcut_thread is not None:
            return

        # The shortcut points at *our* exe with ``--launch=<product_id>``,
        # not at the game directly. That way the shortcut still goes
        # through Shantytown's auth / verify / update path, instead of
        # bypassing it and having the game complain about a stale token.
        name = (self._name_input.text().strip() or self._default_name)
        # Icon source: prefer whatever's currently in the path field
        # (the user may have edited it but not saved yet), fall back to
        # the persisted exe. ``shortcuts.create_desktop_shortcut`` itself
        # falls through to Shantytown's own icon if neither resolves.
        # Resolve on the main thread — ``GameStore`` and ``Path.is_file``
        # are fast and we don't want the worker touching shared state.
        icon_path = self._resolve_icon_path()

        # Surface the in-flight state.
        self._shortcut_btn.setEnabled(False)
        self._shortcut_btn.setText(t("game_settings.creating_shortcut"))
        self._shortcut_spinner.setVisible(True)
        self._pending_shortcut_name = name

        thread = QThread(self)
        worker = _ShortcutWorker(
            name=name,
            product_id=self._installed.product_id,
            icon_path=icon_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Bound-method (not lambda) so ``done()`` can disconnect this
        # specific slot if the user closes the dialog mid-flight without
        # cancelling the thread's quit/cleanup chain.
        worker.finished.connect(self._on_shortcut_done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._shortcut_thread = thread
        self._shortcut_worker = worker
        thread.start()

    def _on_shortcut_done(
        self, success: bool, lnk_path: str, error: str
    ) -> None:
        # Restore button regardless of outcome (no-op if we're about
        # to close on success, but matters for the failure path where
        # the dialog stays open).
        self._shortcut_btn.setEnabled(True)
        self._shortcut_btn.setText(t("game_settings.create_shortcut"))
        self._shortcut_spinner.setVisible(False)
        name = self._pending_shortcut_name
        self._shortcut_thread = None
        self._shortcut_worker = None
        self._pending_shortcut_name = ""

        if not success:
            QMessageBox.warning(
                self,
                t("game_settings.shortcut.failed.title"),
                t("game_settings.shortcut.failed.body", error=error),
            )
            return
        # Hand off to the parent (MainWindow) to render the success
        # toast, then close — the user said "그냥 dialog 닫혀" so we
        # don't gate this on form validation. ``lnk_path`` is unused
        # at present; emit name for the toast text.
        del lnk_path
        self.shortcut_created.emit(
            t("game_settings.shortcut.success.body", name=name)
        )
        self.accept()

    def done(self, r: int) -> None:
        """Detach any in-flight shortcut worker before closing.

        ``QThread`` is parented to ``self``; if we let the dialog get
        destroyed while the thread is still running, Qt aborts the
        process with "Destroyed while thread is still running". Solve
        by re-parenting the thread to ``None`` and disconnecting the
        slot that would call back into this (about-to-be-deleted)
        dialog. The thread's own ``thread.quit`` + ``deleteLater``
        chain is left intact so it self-cleans when the PowerShell
        call returns. The .lnk still gets written either way.
        """
        if self._shortcut_thread is not None:
            if self._shortcut_worker is not None:
                try:
                    self._shortcut_worker.finished.disconnect(
                        self._on_shortcut_done
                    )
                except (TypeError, RuntimeError):
                    pass
            self._shortcut_thread.setParent(None)
            self._shortcut_thread = None
            self._shortcut_worker = None
        super().done(r)

    def _resolve_icon_path(self) -> Path | None:
        """Best-effort game-exe path for shortcut icon extraction.

        Checks the live path field first so an unsaved edit is honoured,
        then the persisted ``GameConfig``. Returns ``None`` when neither
        points at an existing file — the shortcut module then falls
        back to Shantytown's own icon.
        """
        candidate_text = self._path_input.text().strip()
        if candidate_text:
            candidate = Path(candidate_text)
            if candidate.is_file():
                return candidate
        existing = self._game_store.get(self._installed.product_id)
        if (
            existing is not None
            and existing.exe_path is not None
            and existing.exe_path.is_file()
        ):
            return existing.exe_path
        return None

    def _save(self) -> None:
        text = self._path_input.text().strip()
        if not text:
            QMessageBox.warning(
                self,
                t("game_settings.empty.title"),
                t("game_settings.empty.body"),
            )
            return
        new_path = Path(text)
        if not new_path.is_file():
            if (
                QMessageBox.question(
                    self,
                    t("game_settings.missing.title"),
                    t("game_settings.missing.body", path=str(new_path)),
                )
                != QMessageBox.StandardButton.Yes
            ):
                return

        # Empty / whitespace-only override means "use the default" —
        # store None rather than the literal blank string.
        name_override = self._name_input.text().strip() or None

        existing = self._game_store.get(self._installed.product_id)
        cfg = GameConfig(
            product_id=self._installed.product_id,
            exe_path=new_path,
            profile_id=existing.profile_id if existing is not None else None,
            favorite=existing.favorite if existing is not None else False,
            last_played_at=(
                existing.last_played_at if existing is not None else None
            ),
            display_name=name_override,
        )
        self._game_store.upsert(cfg)
        self.accept()
