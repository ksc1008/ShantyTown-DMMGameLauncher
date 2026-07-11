"""Main window — game grid + theme switcher + launch orchestration.

The cnf is the single source of truth for the game list (we never write
to it). Card metadata is enriched from ``known_games.json``; per-game
settings live in the ``GameStore``.

Launch orchestration is centralized here:

- Click on a card's status button →
  - "설정 필요": auto-detect exe from ``known_games`` candidates, fall back
    to ``QFileDialog`` if nothing matches. Save the GameConfig and proceed
    to launch.
  - "로그인 필요": open the login dialog inline. On success, retry launch.
  - "실행": run the worker (verify → download → exec).
  - "실행 중": disabled (the card already shows the running state).
- ⚙ button → ``GameSettingsDialog`` for editing exe path.
- Profile dropdown change → write the new ``profile_id`` to GameStore
  immediately. The card re-renders so the status (in particular
  "로그인 필요") reflects the new profile's token state.

The window keeps a ``dict[product_id, Popen]`` of running subprocesses.
A 2-second poll timer drains finished entries and refreshes those cards
from "실행 중" back to "실행".
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QCloseEvent, QIcon, QPalette, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from shantytown.core import telemetry
from shantytown.core.api import DmmApiClient, DmmApiError
from shantytown.core.dmmcfg import get_default_cnf_path, parse_dmmgame_cnf
from shantytown.core.exe_finder import find_exe_candidate
from shantytown.core.i18n import t
from shantytown.core.models import InstalledGame
from shantytown.core.process_finder import find_running_pids, is_pid_alive
from shantytown.store.games import GameConfig, GameStore
from shantytown.store.known_games import KnownGame, load_known_games
from shantytown.store.profiles import Profile, ProfileStore
from shantytown.store.settings import SettingsStore, ThemeMode

from .fluent import current_tokens
from .game_card import CardState, GameCard, compute_state
from .game_settings_dialog import GameSettingsDialog
from .icons import app_icon, render_icon
from .login_dialog import LoginDialog
from .profile_dialog import ProfileDialog
from .progress_dialog import ProgressDialog
from .theme import apply_theme
from .toast import Toast
from .tutorial_dialog import TutorialDialog
from .web_login_dialog import WebLoginDialog
from .webview_login_client import WebviewLoginClient
from .webview_support import webview_available
from .workers import LaunchWorker, utc_now

RUNNING_POLL_INTERVAL_MS = 2000
GRID_SPACING = 12
GRID_MARGIN = 14


@dataclass
class _RunningGame:
    """One game we're tracking as 'running'.

    Two flavours:

    - **Spawned by us**: ``popen`` is set. ``poll()`` is the cheapest
      and most accurate liveness probe for our own subprocess.
    - **Detected externally**: ``popen`` is ``None``; we know only the
      PID from ``psutil`` scanning at startup. We probe via
      ``is_pid_alive`` on each tick.
    """

    pid: int
    popen: subprocess.Popen[bytes] | None = None

    def is_alive(self) -> bool:
        if self.popen is not None:
            return self.popen.poll() is None
        return is_pid_alive(self.pid)

# Toolbar buttons share a flat, slightly elevated look. The "lighter
# than window" effect comes from ``palette(button)`` (which our theme
# palettes set to ~+10 lightness over the window). Border is removed
# entirely; hover lifts to ``palette(midlight)``.
_TOOLBAR_BUTTON = (
    "QPushButton { background-color: palette(button); color: palette(button-text); "
    "border: none; border-radius: 4px; padding: 6px 14px; min-height: 22px; }"
    "QPushButton:hover:!disabled { background-color: palette(midlight); }"
    "QPushButton:disabled { color: palette(placeholder-text); }"
)
# Square icon-only toolbar variant. Same colour treatment, fixed size,
# no horizontal padding so the icon centres cleanly.
_ICON_BUTTON = (
    "QPushButton { background-color: palette(button); border: none; "
    "border-radius: 4px; padding: 0px; }"
    "QPushButton:hover { background-color: palette(midlight); }"
)

_THEME_CYCLE: list[ThemeMode] = ["system", "light", "dark"]
_THEME_ICONS: dict[ThemeMode, str] = {
    "system": "auto",
    "light": "sun",
    "dark": "moon",
}
_THEME_TOOLTIP_KEYS: dict[ThemeMode, str] = {
    "system": "main.theme.tooltip.system",
    "light": "main.theme.tooltip.light",
    "dark": "main.theme.tooltip.dark",
}

# Stable failure codes from WebviewLoginClient / the login agent → i18n
# keys. Anything unmapped (e.g. DMM's own server-side error message) is
# shown verbatim.
_WEBVIEW_FAILURE_KEYS: dict[str, str] = {
    "helper_missing": "weblogin.helper_missing",
    "helper_exited": "weblogin.err.helper_exited",
    "helper_error": "weblogin.err.helper_error",
    "timeout": "weblogin.err.timeout",
    "page_load_failed": "weblogin.err.page_load_failed",
    "redirect_without_code": "weblogin.err.redirect_without_code",
}


def _webview_failure_text(reason: str) -> str | None:
    """Localised explanation for a known failure code, else ``None``.

    ``None`` means ``reason`` is a raw, verbatim message from DMM (not one
    of our codes); the caller surfaces it as a copyable site message rather
    than as our own explanation.
    """
    key = _WEBVIEW_FAILURE_KEYS.get(reason)
    if key is None and reason.startswith("form_not_found"):
        key = "weblogin.err.form_not_found"
    return t(key) if key else None


class MainWindow(QMainWindow):
    def __init__(
        self,
        api: DmmApiClient,
        profile_store: ProfileStore,
        game_store: GameStore,
        settings_store: SettingsStore | None = None,
        cnf_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._api = api
        self._profile_store = profile_store
        self._game_store = game_store
        self._settings_store = settings_store
        self._cnf_path = cnf_path or get_default_cnf_path()
        self._known_games: dict[str, KnownGame] = load_known_games()
        self._installed_by_id: dict[str, InstalledGame] = {}
        self._running: dict[str, _RunningGame] = {}
        # The webview login client wraps a warm __loginhelper process,
        # reused across login attempts (spawning Chromium per attempt is
        # too slow). Shut down after a successful game launch / app exit.
        self._webview_client: WebviewLoginClient | None = None
        # (profile_id, product_id) of the login attempt in flight.
        self._webview_login_ctx: tuple[str, str] | None = None
        self._web_dialog: WebLoginDialog | None = None
        # Auto-login (expired-token path): product whose launch just failed
        # with an auth error and is scheduled for an automatic logout+retry,
        # plus the set already retried once so a repeat failure can't loop.
        self._auto_relogin_pending: str | None = None
        self._auto_relogin_attempted: set[str] = set()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(RUNNING_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_running)

        self._cached_installed: list[InstalledGame] = []
        self._current_cols: int = 1
        self._initial_layout_done: bool = False
        # Silent-launch mode. Set by ``begin_silent_launch`` when the
        # app is started via ``--launch=<id>`` (a desktop shortcut).
        # While true, a successful spawn calls ``QApplication.quit()``
        # so the launcher exits cleanly, leaving only the game running.
        # Any path that has to surface UI (errors, missing config, login
        # required) flips it back to false — once the user can see the
        # main window, they're in control and we don't auto-quit.
        self._silent_mode: bool = False

        self._build_ui()
        self.refresh()

    # --- UI ---

    def _build_ui(self) -> None:
        app_name = t("app.name")
        self.setWindowTitle(app_name)
        self.setWindowIcon(app_icon())
        # 2x2 cards (280 + 12 + 280 = 572 + side margins) plus header — give
        # ourselves headroom so the user can shrink without breaking the grid.
        self.setMinimumSize(640, 520)
        self.resize(920, 640)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(GRID_MARGIN, GRID_MARGIN, GRID_MARGIN, GRID_MARGIN)

        # --- header: icon + title left, profile / refresh / help right ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        # Render the icon at the screen's DPR so the rasterised SVG
        # stays crisp on HiDPI displays without forcing every monitor
        # to use a 1x bitmap.
        icon_label = QLabel()
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        logical = QSize(34, 34)
        physical = QSize(
            int(logical.width() * dpr), int(logical.height() * dpr)
        )
        icon_pix = app_icon().pixmap(physical)
        icon_pix.setDevicePixelRatio(dpr)
        icon_label.setPixmap(icon_pix)
        icon_label.setFixedSize(logical)
        toolbar.addWidget(icon_label)

        toolbar.addWidget(QLabel(f"<h1 style='margin:4px;'>{app_name}</h1>"))
        toolbar.addStretch(1)

        self._profile_btn = QPushButton(" " + t("main.profile_button"))
        self._profile_btn.setStyleSheet(_TOOLBAR_BUTTON)
        self._profile_btn.setIconSize(QSize(18, 18))
        self._profile_btn.clicked.connect(self._open_profiles)
        toolbar.addWidget(self._profile_btn)

        self._refresh_btn = QPushButton()
        self._refresh_btn.setStyleSheet(_ICON_BUTTON)
        self._refresh_btn.setFixedSize(36, 36)
        self._refresh_btn.setIconSize(QSize(20, 20))
        self._refresh_btn.setToolTip(t("main.refresh_button.tooltip"))
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_btn)

        self._help_btn = QPushButton()
        self._help_btn.setStyleSheet(_ICON_BUTTON)
        self._help_btn.setFixedSize(36, 36)
        self._help_btn.setIconSize(QSize(20, 20))
        self._help_btn.setToolTip(t("main.help_button.tooltip"))
        self._help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._help_btn.clicked.connect(self._open_tutorial)
        toolbar.addWidget(self._help_btn)

        root.addLayout(toolbar)

        # --- grid ---
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._grid.setSpacing(GRID_SPACING)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(self._grid_host)
        root.addWidget(self._scroll, stretch=1)

        # --- footer: theme cycle pinned bottom-right ---
        footer = QHBoxLayout()
        footer.addStretch(1)
        self._theme_btn = QPushButton()
        self._theme_btn.setStyleSheet(_ICON_BUTTON)
        self._theme_btn.setFixedSize(36, 36)
        self._theme_btn.setIconSize(QSize(20, 20))
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._cycle_theme)
        footer.addWidget(self._theme_btn)
        root.addLayout(footer)

        self.setCentralWidget(container)

        # Reflect current theme in the toggle button on first paint.
        self._sync_theme_button()
        self._sync_toolbar_icons()

    # --- public API ---

    def refresh(self) -> None:
        try:
            installed = parse_dmmgame_cnf(self._cnf_path)
        except FileNotFoundError:
            installed = []
            QMessageBox.warning(
                self,
                t("main.cnf_missing.title"),
                t("main.cnf_missing.body", path=str(self._cnf_path)),
            )
        self._installed_by_id = {g.product_id: g for g in installed}
        self._cached_installed = installed
        self._scan_external_running_games(installed)
        self._current_cols = self._compute_columns()
        self._render_cards(installed)
        self._sync_toolbar_icons()

    def _scan_external_running_games(
        self, installed: list[InstalledGame]
    ) -> None:
        """Find games already running outside this session.

        Called from ``refresh()``; entries we already track (because
        we spawned them ourselves) are left untouched. Newly-found
        external processes get added with a PID-only ``_RunningGame``,
        and the poll timer starts so we notice when they exit.
        """
        targets: dict[str, Path] = {}
        for game in installed:
            if game.product_id in self._running:
                continue
            cfg = self._game_store.get(game.product_id)
            if cfg is not None and cfg.exe_path is not None:
                targets[game.product_id] = cfg.exe_path
        if not targets:
            return
        matches = find_running_pids(list(targets.values()))
        added = False
        for product_id, exe_path in targets.items():
            pid = matches.get(exe_path)
            if pid is not None:
                self._running[product_id] = _RunningGame(pid=pid)
                added = True
        if added and not self._poll_timer.isActive():
            self._poll_timer.start()

    # --- responsive grid ---

    def _compute_columns(self) -> int:
        viewport = self._scroll.viewport()
        width = viewport.width() if viewport is not None else self.width()
        # ``viewport.width()`` already accounts for the central widget's
        # margins and the scroll-area frame — don't subtract those again.
        if width <= 0:
            return 1
        cols = max(
            1,
            int((width + GRID_SPACING) // (GameCard.MIN_WIDTH + GRID_SPACING)),
        )
        return min(cols, 6)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        new_cols = self._compute_columns()
        if new_cols != self._current_cols:
            self._current_cols = new_cols
            # Re-layout existing cards into the new column count rather
            # than rebuilding them — cheaper and preserves any unsaved
            # interaction state on the cards.
            self._reflow_cards()

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        if self._initial_layout_done:
            return
        self._initial_layout_done = True
        # The viewport has its real width only after the window is on
        # screen — defer to the next event-loop tick, then run one
        # reflow so the grid uses the right column count from the
        # first paint instead of waiting for the user to resize.
        QTimer.singleShot(0, self._initial_reflow)

    def closeEvent(self, event: QCloseEvent | None) -> None:
        # The warm __loginhelper (if any) must not outlive the app.
        self._shutdown_webview_helper()
        super().closeEvent(event)

    def _initial_reflow(self) -> None:
        new_cols = self._compute_columns()
        if new_cols != self._current_cols:
            self._current_cols = new_cols
            self._reflow_cards()

    def _reflow_cards(self) -> None:
        cards: list[GameCard] = []
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if isinstance(w, GameCard):
                cards.append(w)
        for i, card in enumerate(cards):
            row, col = divmod(i, max(1, self._current_cols))
            self._grid.addWidget(card, row, col)

    # --- rendering ---

    def _render_cards(self, installed: list[InstalledGame]) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()

        default = self._profile_store.get_default()
        all_profiles = self._profile_store.list()
        cols = max(1, self._current_cols)

        for i, game in enumerate(installed):
            cfg = self._game_store.get(game.product_id)
            bound = self._resolve_profile_for(game.product_id)
            known = self._known_games.get(game.product_id)
            is_running = game.product_id in self._running
            card = GameCard(
                installed=game,
                known=known,
                config=cfg,
                profiles=all_profiles,
                bound_profile=bound,
                default_profile=default,
                is_running=is_running,
            )
            card.status_clicked.connect(self._on_status_clicked)
            card.settings_clicked.connect(self._open_settings_dialog)
            card.profile_changed.connect(self._on_profile_changed)
            row, col = divmod(i, cols)
            self._grid.addWidget(card, row, col)

    # --- helpers ---

    def _resolve_profile_for(self, product_id: str) -> Profile | None:
        cfg = self._game_store.get(product_id)
        if cfg is not None and cfg.profile_id is not None:
            p = self._profile_store.get(cfg.profile_id)
            if p is not None:
                return p
        return self._profile_store.get_default()

    # --- theme ---

    def _cycle_theme(self) -> None:
        current: ThemeMode = (
            self._settings_store.get().theme
            if self._settings_store is not None
            else "system"
        )
        next_idx = (_THEME_CYCLE.index(current) + 1) % len(_THEME_CYCLE)
        next_mode = _THEME_CYCLE[next_idx]
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        apply_theme(app, next_mode)
        if self._settings_store is not None:
            # Preserve the other settings fields (tutorial_completed,
            # login_method) — only the theme is changing here.
            current_settings = self._settings_store.get()
            self._settings_store.update(
                replace(current_settings, theme=next_mode)
            )
        # Per-widget stylesheets cache resolved palette colors at parse
        # time. Re-applying the same QSS string after the palette swap
        # forces Qt to re-evaluate ``palette(...)`` refs against the
        # fresh palette — without this, the three persistent toolbar
        # buttons would keep rendering with the old palette's colors.
        self._refresh_persistent_styling()
        self._sync_theme_button()
        self._sync_toolbar_icons()
        self.refresh()

    def _refresh_persistent_styling(self) -> None:
        self._theme_btn.setStyleSheet(_ICON_BUTTON)
        self._profile_btn.setStyleSheet(_TOOLBAR_BUTTON)
        self._refresh_btn.setStyleSheet(_ICON_BUTTON)
        self._help_btn.setStyleSheet(_ICON_BUTTON)

    def _sync_theme_button(self) -> None:
        current: ThemeMode = (
            self._settings_store.get().theme
            if self._settings_store is not None
            else "system"
        )
        tokens = current_tokens(self)
        # Use the foreground token so the icon contrasts against
        # palette(button) on both light and dark backgrounds.
        text_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        icon = QIcon(render_icon(_THEME_ICONS[current], 20, text_color))
        self._theme_btn.setIcon(icon)
        self._theme_btn.setToolTip(t(_THEME_TOOLTIP_KEYS[current]))
        # Suppress lint noise for the "unused" tokens import — we keep
        # it around for future per-mode accents on the toolbar.
        del tokens

    def _sync_toolbar_icons(self) -> None:
        """Recolor toolbar icons (profile/refresh/help) to match the theme."""
        text_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        self._profile_btn.setIcon(QIcon(render_icon("people", 18, text_color)))
        self._refresh_btn.setIcon(QIcon(render_icon("refresh", 20, text_color)))
        self._help_btn.setIcon(QIcon(render_icon("help", 20, text_color)))

    def _open_tutorial(self) -> None:
        TutorialDialog(self).exec()

    def show_toast(self, message: str) -> None:
        """Slide a brief positive notification down from the top of the
        main window. Replaces modal "success!" QMessageBox prompts for
        low-stakes confirmations like "shortcut created"."""
        central = self.centralWidget()
        if central is None:
            return
        Toast(central, message).show_animated()

    # --- card actions ---

    def _on_status_clicked(self, product_id: str) -> None:
        installed = self._installed_by_id.get(product_id)
        if installed is None:
            return
        cfg = self._game_store.get(product_id)
        bound = self._resolve_profile_for(product_id)
        state = compute_state(cfg, bound, product_id in self._running)

        if state is CardState.RUNNING:
            return  # button is disabled but defensive

        if state is CardState.NEEDS_SETUP:
            if not self._configure_exe_inline(installed):
                return
            self.refresh()
            # Re-resolve and continue: state may now be NEEDS_LOGIN or READY.
            self._on_status_clicked(product_id)
            return

        if state is CardState.NEEDS_LOGIN:
            if bound is None:
                QMessageBox.warning(
                    self,
                    "프로필 필요",
                    "프로필이 없습니다. 프로필 관리에서 먼저 만들어주세요.",
                )
                return
            self._login_then_launch(bound, product_id)
            return

        # READY
        self._launch_game(product_id)

    def _configure_exe_inline(self, installed: InstalledGame) -> bool:
        """Auto-detect the exe; fall back to QFileDialog. Returns True on save."""
        known = self._known_games.get(installed.product_id)
        candidates = known.exe_name_candidates if known is not None else ()

        detected = find_exe_candidate(installed.install_path, candidates)
        if detected is not None:
            ok = (
                QMessageBox.question(
                    self,
                    t("main.exe_detected.title"),
                    t("main.exe_detected.body", name=detected.name),
                )
                == QMessageBox.StandardButton.Yes
            )
            if ok:
                self._save_exe(installed, detected)
                return True
            # User said no — fall through to manual pick.

        path_str, _filter = QFileDialog.getOpenFileName(
            self,
            t("main.choose_exe.title"),
            str(installed.install_path)
            if installed.install_path.exists()
            else str(Path.home()),
            t("main.exe_filter"),
        )
        if not path_str:
            return False
        self._save_exe(installed, Path(path_str))
        return True

    def _save_exe(self, installed: InstalledGame, exe_path: Path) -> None:
        existing = self._game_store.get(installed.product_id)
        # Preserve every other field (esp. the user's display_name override)
        # when only the exe path changes.
        if existing is not None:
            cfg = replace(existing, exe_path=exe_path)
        else:
            cfg = GameConfig(product_id=installed.product_id, exe_path=exe_path)
        self._game_store.upsert(cfg)
        # Best-effort telemetry ping; no-op unless the test flag is set.
        telemetry.report_exe_path(
            installed.product_id, exe_path, installed.install_path
        )

    def _open_settings_dialog(self, product_id: str) -> None:
        installed = self._installed_by_id.get(product_id)
        if installed is None:
            return
        dialog = GameSettingsDialog(
            installed=installed,
            known=self._known_games.get(product_id),
            game_store=self._game_store,
            parent=self,
        )
        # Toast surfaces inside the main window after the dialog closes
        # so the user sees the success-green slide-down behind / above
        # the (already-dismissed) settings UI.
        dialog.shortcut_created.connect(self.show_toast)
        if dialog.exec() == GameSettingsDialog.DialogCode.Accepted:
            cfg = self._game_store.get(product_id)
            if cfg is not None and cfg.exe_path is not None:
                telemetry.report_exe_path(
                    product_id, cfg.exe_path, installed.install_path
                )
            self.refresh()

    def _on_profile_changed(
        self, product_id: str, profile_id: object
    ) -> None:
        existing = self._game_store.get(product_id)
        normalized: str | None = (
            str(profile_id) if isinstance(profile_id, str) and profile_id else None
        )
        if existing is None:
            self._game_store.upsert(
                GameConfig(product_id=product_id, profile_id=normalized)
            )
        else:
            # replace() keeps display_name and every other field intact.
            self._game_store.upsert(replace(existing, profile_id=normalized))
        self.refresh()

    def _open_profiles(self) -> None:
        dialog = ProfileDialog(
            self._profile_store,
            self._api,
            parent=self,
            settings_store=self._settings_store,
        )
        dialog.exec()
        self.refresh()

    # --- launch flow ---

    def _effective_login_method(self) -> str:
        """The login method actually used.

        Webview is honoured only when the ``__loginhelper`` is actually
        available (``webview_available()``). Otherwise the browser flow is
        forced regardless of the saved ``login_method`` — so a browser-only
        install (no helper shipped) never reaches the webview path. Helper
        presence *is* the gate; no ``--debug`` flag is needed.
        """
        if not webview_available() or self._settings_store is None:
            return "browser"
        return self._settings_store.get().login_method

    def _auto_login_active(self) -> bool:
        """Whether auto-login behaviours apply right now.

        Gated on the webview method being effective *and* the auto-login
        setting being on — the toggle is only offered under webview, so
        auto-login never drives the browser flow.
        """
        if self._settings_store is None:
            return False
        if self._effective_login_method() != "webview":
            return False
        return self._settings_store.get().auto_login

    def _login_then_launch(self, profile: Profile, product_id: str) -> None:
        method = self._effective_login_method()
        if method == "webview":
            # Webview mode: collect/confirm credentials in the form, then
            # drive the headless login agent to mint a token. The dialog
            # stays open as a progress view and is closed on success or
            # shown an error on failure (see the agent callbacks). With
            # auto-login on, a profile with saved credentials submits
            # automatically — no button click needed.
            web_dialog = WebLoginDialog(
                profile,
                self._profile_store,
                parent=self,
                auto_login=self._auto_login_active(),
            )
            self._web_dialog = web_dialog
            web_dialog.login_requested.connect(
                lambda email, password, pid=profile.id, prod=product_id: (
                    self._start_webview_login(pid, email, password, prod)
                )
            )
            web_dialog.exec()
            self._web_dialog = None
            # The dialog closed — on success the login already finished; on
            # cancel/close one may still be in flight, so abort it. The
            # helper process itself stays warm for the next attempt (it is
            # shut down after a successful game launch or on app exit).
            self._abort_webview_login()
            self.refresh()
            return
        dialog = LoginDialog(self._api, parent=self)
        dialog.token_issued.connect(
            lambda token, email, pid=profile.id, prod=product_id: (
                self._on_inline_token_issued(pid, token, email, prod)
            )
        )
        dialog.exec()

    def _on_inline_token_issued(
        self, profile_id: str, token: str, email: object, product_id: str
    ) -> None:
        existing = self._profile_store.get(profile_id)
        if existing is None:
            return
        new_email = (
            str(email) if isinstance(email, str) and email else existing.email
        )
        self._profile_store.update(
            Profile(
                id=existing.id,
                name=existing.name,
                token=token,
                created_at=existing.created_at,
                last_used_at=existing.last_used_at,
                email=new_email,
                password=existing.password,
            )
        )
        self.refresh()
        self._launch_game(product_id)

    # --- webview login (via the __loginhelper process) ---

    def _ensure_webview_client(self) -> WebviewLoginClient:
        """The lazily-created, signal-wired login client (one per window).

        Created once and reused so the underlying ``__loginhelper``
        process stays warm across login attempts.
        """
        if self._webview_client is None:
            client = WebviewLoginClient(self)
            client.engineReady.connect(self._on_webview_engine_ready)
            client.succeeded.connect(self._on_webview_succeeded)
            client.failed.connect(self._on_webview_failed)
            self._webview_client = client
        return self._webview_client

    def _start_webview_login(
        self, profile_id: str, email: str, password: str, product_id: str
    ) -> None:
        """Kick off the webview login for ``profile_id`` via the helper.

        The dialog already shows "웹뷰 로드중" (enter_progress). The
        ``__loginhelper`` process is spawned asynchronously on the first
        attempt and reused afterwards; when the helper reports its engine
        is up we flip the status to "로그인 중". A missing helper just
        fails gracefully.
        """
        try:
            login_url = self._api.get_login_url()
        except DmmApiError as e:
            self._report_webview_failure(str(e))
            return
        self._webview_login_ctx = (profile_id, product_id)
        self._ensure_webview_client().start(login_url, email, password)

    def _on_webview_engine_ready(self) -> None:
        if self._web_dialog is not None:
            self._web_dialog.set_progress_status(t("weblogin.progress"))

    def _on_webview_succeeded(self, code: str) -> None:
        ctx, self._webview_login_ctx = self._webview_login_ctx, None
        if ctx is None:
            return
        profile_id, product_id = ctx
        self._on_webview_code(profile_id, code, product_id)

    def _on_webview_failed(self, reason: str) -> None:
        self._webview_login_ctx = None
        self._report_webview_failure(reason)

    def _on_webview_code(
        self, profile_id: str, code: str, product_id: str
    ) -> None:
        try:
            token = self._api.issue_token(code)
        except DmmApiError as e:
            self._report_webview_failure(str(e))
            return
        existing = self._profile_store.get(profile_id)
        if existing is None:
            return
        self._profile_store.update(replace(existing, token=token))
        # Close the progress dialog, then launch once the modal loop has
        # unwound (avoids opening the launch progress dialog re-entrantly).
        if self._web_dialog is not None:
            self._web_dialog.accept()
        self.refresh()
        QTimer.singleShot(0, lambda: self._launch_game(product_id))

    def _abort_webview_login(self) -> None:
        """Abort an in-flight login; the helper process stays warm."""
        self._webview_login_ctx = None
        if self._webview_client is not None:
            self._webview_client.abort()

    def _shutdown_webview_helper(self) -> None:
        """Terminate the warm ``__loginhelper`` process (if any)."""
        if self._webview_client is not None:
            self._webview_client.shutdown()

    def _report_webview_failure(self, reason: str) -> None:
        # The raw reason code stays on the console for diagnostics.
        print(f"[webview-login] failed: {reason}", file=sys.stderr)
        text = _webview_failure_text(reason)
        # If the credential form is still open, surface the error there (it's
        # in its progress state) so the user can retry; otherwise toast.
        if self._web_dialog is not None:
            if text is not None:
                self._web_dialog.show_error(text)
            else:
                # Unmapped → DMM's own message: show it verbatim + copyable.
                self._web_dialog.show_error(site_message=reason)
        else:
            self.show_toast(
                t("webview_login.failed", reason=text if text is not None else reason)
            )

    def _launch_game(self, product_id: str) -> None:
        installed = self._installed_by_id.get(product_id)
        cfg = self._game_store.get(product_id)
        if installed is None or cfg is None or cfg.exe_path is None:
            QMessageBox.warning(
                self,
                t("main.cannot_launch.title"),
                t("main.cannot_launch.body"),
            )
            return

        profile = self._resolve_profile_for(product_id)
        if profile is None:
            QMessageBox.warning(
                self,
                t("main.no_profile.title"),
                t("main.no_profile.body"),
            )
            return
        if not profile.token:
            self._login_then_launch(profile, product_id)
            return

        thread = QThread(self)
        worker = LaunchWorker(
            api=self._api,
            token=profile.token,
            product_id=installed.product_id,
            game_type=installed.game_type,
            install_dir=installed.install_path,
            exe_path=cfg.exe_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        dialog = ProgressDialog(t("main.progress_dialog.title"), thread, parent=self)
        worker.progress.connect(dialog.set_progress)
        # Expired/invalid token. With auto-login on (and not already retried
        # once for this product), silently close the dialog and schedule an
        # automatic logout + re-login after exec() returns. Otherwise fall
        # back to the manual logout button on the error dialog.
        auto_relogin = (
            self._auto_login_active()
            and product_id not in self._auto_relogin_attempted
        )
        worker.auth_invalid.connect(
            lambda dlg=dialog, prof=profile, pid=product_id, auto=auto_relogin: (
                self._on_launch_auth_invalid(dlg, prof, pid, auto)
            )
        )
        worker.finished.connect(dialog.finish)

        worker.finished.connect(
            lambda success, message, popen, pid=product_id, prof=profile, c=cfg: (
                self._on_launch_finished(success, message, popen, pid, prof, c)
            )
        )
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()
        dialog.exec()

        # Auto-login: the launch failed on an expired token — log out and
        # re-run the launch (which now routes through the login flow, and
        # auto-submits the saved credentials). Bounded to one retry per
        # product so a persistently-rejected token can't loop.
        if self._auto_relogin_pending == product_id:
            self._auto_relogin_pending = None
            self._auto_relogin_attempted.add(product_id)
            self._logout_from_launch(profile, product_id)
            self._launch_game(product_id)

    def _on_launch_auth_invalid(
        self,
        dialog: ProgressDialog,
        profile: Profile,
        product_id: str,
        auto: bool,
    ) -> None:
        """React to a launch's expired/invalid-token signal.

        Auto-login: mark the product for an automatic logout+retry (handled
        after ``exec()`` returns) and close the progress dialog so the user
        never sees the error. Otherwise, offer the manual logout button.
        """
        if auto:
            self._auto_relogin_pending = product_id
            # Close the modal dialog on the next tick (finish() runs right
            # after this signal; deferring lets it settle first).
            QTimer.singleShot(0, dialog.reject)
        else:
            dialog.enable_logout(
                lambda: self._logout_from_launch(profile, product_id)
            )

    def _logout_from_launch(self, profile: Profile, product_id: str) -> None:
        """Clear the profile's token in response to an auth failure.

        Invoked by the logout button the ProgressDialog shows when a
        launch fails with an expired/invalid token. Re-reads the profile
        from the store (it may have changed since the launch began) and
        writes it back with ``token=None`` so the next launch routes
        through the login flow. Silent-mode launches have already
        revealed the main window by this point, so the toast is visible.
        """
        existing = self._profile_store.get(profile.id)
        if existing is not None and existing.token:
            self._profile_store.update(
                Profile(
                    id=existing.id,
                    name=existing.name,
                    token=None,
                    created_at=existing.created_at,
                    last_used_at=existing.last_used_at,
                    email=existing.email,
                    password=existing.password,
                )
            )
        self.refresh()
        self.show_toast(t("main.logout_done", name=profile.name))

    def _on_launch_finished(
        self,
        success: bool,
        message: str,
        popen: object,
        product_id: str,
        profile: Profile,
        cfg: GameConfig,
    ) -> None:
        if not success:
            # Auto-login is about to log out and retry this product (the
            # dialog was closed silently), so don't surface the failure —
            # the retry runs once exec() returns.
            if self._auto_relogin_pending == product_id:
                return
            # The progress dialog already showed the error to the user.
            # In silent mode the main window was never visible, so once
            # they dismiss the error there's nowhere to go — surface
            # the window so they have a place to retry / inspect state.
            if self._silent_mode and not self.isVisible():
                self._silent_mode = False
                self.show()
                self.raise_()
                self.activateWindow()
            return
        # A launch succeeded → this product is healthy again; drop any
        # auto-relogin bookkeeping so a future expired token can retry.
        self._auto_relogin_attempted.discard(product_id)
        # Stamp last_used / last_played
        self._profile_store.update(
            Profile(
                id=profile.id,
                name=profile.name,
                token=profile.token,
                created_at=profile.created_at,
                last_used_at=utc_now(),
                email=profile.email,
                password=profile.password,
            )
        )
        self._game_store.upsert(replace(cfg, last_played_at=utc_now()))
        # The game is up — the warm login helper has served its purpose.
        self._shutdown_webview_helper()
        # Track the running subprocess so the card flips to "실행 중".
        if isinstance(popen, subprocess.Popen):
            self._running[product_id] = _RunningGame(
                pid=popen.pid, popen=popen
            )
            if not self._poll_timer.isActive():
                self._poll_timer.start()
        self.refresh()
        # Silent-mode success: game spawned cleanly with no UI required.
        # Quit the launcher process — the game is detached (DETACHED_PROCESS)
        # and survives our exit on its own.
        if self._silent_mode and not self.isVisible():
            self._silent_mode = False
            app = QApplication.instance()
            if app is not None:
                app.quit()

    # --- silent / external launch entry points ---

    def begin_silent_launch(self, product_id: str) -> None:
        """Start a launch flow as if from a desktop shortcut.

        Triggered when the app was started with ``--launch=<id>`` and
        no other instance was already running. The main window stays
        hidden; only the progress dialog is visible while files verify
        / download. On clean success ``_on_launch_finished`` calls
        ``QApplication.quit()`` so the launcher exits and only the
        game's own process remains.

        Anything that needs user input — game not in the install
        index, exe path missing, profile missing, token expired,
        cnf file unreadable — surfaces the main window and hands off
        to the normal click-handler path so the user resolves it
        with the full UI in front of them.
        """
        self._silent_mode = True
        # ``__init__`` already called ``refresh()``, but a stale
        # ``dmmgame.cnf`` race (game just installed/uninstalled while
        # the shortcut was clicked) is conceivable. Cheap to redo.
        self.refresh()

        if product_id not in self._installed_by_id:
            self._reveal_silent_failure(
                t("silent_launch.not_installed.title"),
                t(
                    "silent_launch.not_installed.body",
                    product_id=product_id,
                ),
            )
            return

        if product_id in self._running:
            # Spec: 게임이 이미 실행 중이면 아무것도 하지 않는다.
            self._silent_mode = False
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return

        cfg = self._game_store.get(product_id)
        bound = self._resolve_profile_for(product_id)
        state = compute_state(cfg, bound, is_running=False)

        if state in (CardState.NEEDS_SETUP, CardState.NEEDS_LOGIN):
            # User input required — reveal the window and dispatch
            # through the same path as a card click.
            self._silent_mode = False
            self.show()
            self.raise_()
            self.activateWindow()
            self._on_status_clicked(product_id)
            return

        # READY — drive the launch worker. The progress dialog is its
        # own top-level window; the hidden main window stays hidden.
        self._launch_game(product_id)

    def handle_external_launch(self, product_id: str) -> None:
        """A second ``--launch`` invocation arrived over the IPC pipe.

        We're already running with the user engaged, so this isn't
        silent — show whatever the click flow would show. If the game
        is already running we no-op (matches the silent-launch rule
        and avoids spawning a duplicate).
        """
        self.refresh()
        if product_id not in self._installed_by_id:
            QMessageBox.warning(
                self,
                t("silent_launch.not_installed.title"),
                t(
                    "silent_launch.not_installed.body",
                    product_id=product_id,
                ),
            )
            return
        if product_id in self._running:
            return
        self._on_status_clicked(product_id)

    def _reveal_silent_failure(self, title: str, body: str) -> None:
        """Surface the main window and warn the user, exiting silent mode."""
        self._silent_mode = False
        self.show()
        self.raise_()
        self.activateWindow()
        QMessageBox.warning(self, title, body)

    # --- running-state polling ---

    def _poll_running(self) -> None:
        finished: list[str] = []
        for product_id, entry in self._running.items():
            if not entry.is_alive():
                finished.append(product_id)
        for product_id in finished:
            self._running.pop(product_id, None)
        if finished:
            self.refresh()
        if not self._running:
            self._poll_timer.stop()
