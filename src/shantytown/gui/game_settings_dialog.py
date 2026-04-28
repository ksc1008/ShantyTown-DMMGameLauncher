"""Per-game settings dialog.

Triggered from the ⚙ button on each card. Right now it owns just the
exe path edit, but lives in its own module so future per-game settings
(force-verify, custom launch args, …) have somewhere to land without
spaghettifying the card.
"""

from __future__ import annotations

from pathlib import Path

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
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.known_games import KnownGame


class GameSettingsDialog(QDialog):
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

        existing = game_store.get(installed.product_id)
        self._initial_exe: Path | None = (
            existing.exe_path if existing is not None else None
        )

        display_name = (
            known.display_name if known is not None else installed.product_id
        )
        self.setWindowTitle(t("game_settings.title", name=display_name))
        self.setModal(True)
        self.setFixedSize(560, 220)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{display_name}</b>"))
        root.addWidget(
            QLabel(
                f"{t('game_settings.install_path')} "
                f"<code>{installed.install_path}</code>"
            )
        )

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

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
        existing = self._game_store.get(self._installed.product_id)
        cfg = GameConfig(
            product_id=self._installed.product_id,
            exe_path=new_path,
            profile_id=existing.profile_id if existing is not None else None,
            favorite=existing.favorite if existing is not None else False,
            last_played_at=(
                existing.last_played_at if existing is not None else None
            ),
        )
        self._game_store.upsert(cfg)
        self.accept()
