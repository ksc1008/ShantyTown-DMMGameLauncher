"""Game card widget — Fluent-tone, click-to-act, animated hover.

Layout:

    ┌───────────────────────────────────────────────┐
    │ [icon] Game Display Name                [⚙]  │
    │                                               │
    │ 프로필: [▼ dropdown                        ]  │
    │                                               │
    │ 상태                                          │
    └───────────────────────────────────────────────┘

The card surface is painted in ``paintEvent``, not via QSS — that lets
us interpolate the background color smoothly between the idle and
hover tints. ``QPropertyAnimation`` drives a ``hoverT`` property
(0 = idle, 1 = hover); ``OutCubic`` easing gives the FastEaseOut feel.

Hover suppression: the QFrame's :hover state would also fire when the
mouse is over the profile dropdown or settings button. We don't want
that — those controls capture their own clicks, and lighting up the
whole card while you're targeting a sub-action feels off. An event
filter on those two children sets a ``_child_hovered`` flag and
animates the card back to idle.

The whole card is the click target. ``mouseReleaseEvent`` emits
``status_clicked`` only if the mouse is still inside the card
(matches the standard "press, drag away, no click" behavior).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PyQt6.QtCore import (  # type: ignore[attr-defined]
    QEasingCurve,
    QEvent,
    QFileInfo,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFileIconProvider,
    QFrame,
    QGraphicsColorizeEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from shantytown.core.i18n import t
from shantytown.core.models import InstalledGame
from shantytown.store.games import GameConfig
from shantytown.store.known_games import KnownGame
from shantytown.store.profiles import Profile

from .fluent import FluentTokens, current_tokens
from .icons import render_icon


class CardState(Enum):
    NEEDS_SETUP = "needs_setup"
    NEEDS_LOGIN = "needs_login"
    READY = "ready"
    RUNNING = "running"


_STATE_LABEL_KEYS: dict[CardState, str] = {
    CardState.NEEDS_SETUP: "card.state.needs_setup",
    CardState.NEEDS_LOGIN: "card.state.needs_login",
    CardState.RUNNING: "card.state.running",
    CardState.READY: "card.state.ready",
}


def _state_label(state: CardState) -> str:
    return t(_STATE_LABEL_KEYS[state])


def get_exe_icon(exe_path: Path | None) -> QIcon | None:
    """Return the system icon for ``exe_path`` if it exists."""
    if exe_path is None or not exe_path.is_file():
        return None
    return QFileIconProvider().icon(QFileInfo(str(exe_path)))


def compute_state(
    config: GameConfig | None,
    bound_profile: Profile | None,
    is_running: bool,
) -> CardState:
    if is_running:
        return CardState.RUNNING
    if config is None or config.exe_path is None:
        return CardState.NEEDS_SETUP
    if bound_profile is None or not bound_profile.token:
        return CardState.NEEDS_LOGIN
    return CardState.READY


def _state_text_color(state: CardState, tokens: FluentTokens) -> str:
    return {
        CardState.READY: tokens.state_ready,
        CardState.NEEDS_LOGIN: tokens.state_login,
        CardState.RUNNING: tokens.state_running,
        CardState.NEEDS_SETUP: tokens.state_setup,
    }[state]


def _hover_color(state: CardState, tokens: FluentTokens) -> str:
    return {
        CardState.READY: tokens.surface_hover_ready,
        CardState.NEEDS_LOGIN: tokens.surface_hover_login,
        CardState.RUNNING: tokens.surface,
        CardState.NEEDS_SETUP: tokens.surface_hover_setup,
    }[state]


def _blend_hex(c1: str, c2: str, t: float) -> str:
    """Linear-interpolate two ``#rrggbb`` colors. ``t`` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


HOVER_DURATION_MS = 180
CHILD_HOVER_DURATION_MS = 150
SETTINGS_HOVER_STRENGTH = 0.85
COMBO_HOVER_STRENGTH = 0.18


class GameCard(QFrame):
    """One game's tile in the main grid."""

    status_clicked = pyqtSignal(str)
    settings_clicked = pyqtSignal(str)
    profile_changed = pyqtSignal(str, object)

    # Min/max width caps so the responsive grid in MainWindow can keep
    # cards readable as the window stretches.
    MIN_WIDTH = 280
    MAX_WIDTH = 380

    def __init__(
        self,
        installed: InstalledGame,
        known: KnownGame | None,
        config: GameConfig | None,
        profiles: list[Profile],
        bound_profile: Profile | None,
        default_profile: Profile | None,
        is_running: bool,
    ) -> None:
        super().__init__()
        self._installed = installed
        self._press_pos: QPoint | None = None
        self._tokens = current_tokens(self)
        self._state = compute_state(config, bound_profile, is_running)
        self._hover_t: float = 0.0
        self._child_hovered: bool = False

        self.setObjectName("GameCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # We paint our own background — opt out of Qt's styled background
        # so QSS can't fight with the painter.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.MIN_WIDTH, 170)
        self.setMaximumWidth(self.MAX_WIDTH)
        self.setMouseTracking(True)
        if self._state is not CardState.RUNNING:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"hoverT", self)
        self._anim.setDuration(HOVER_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._build_ui(known, config, profiles, default_profile)
        self._wire_child_hover_effects()

    # --- public ---

    @property
    def product_id(self) -> str:
        return self._installed.product_id

    # --- pyqtProperty for animation ---

    def _get_hover_t(self) -> float:
        return self._hover_t

    def _set_hover_t(self, value: float) -> None:
        self._hover_t = value
        self.update()

    hoverT = pyqtProperty(float, fget=_get_hover_t, fset=_set_hover_t)

    # --- layout ---

    def _build_ui(
        self,
        known: KnownGame | None,
        config: GameConfig | None,
        profiles: list[Profile],
        default_profile: Profile | None,
    ) -> None:
        # Title precedence:
        #   1. user override saved on the GameConfig (rename feature)
        #   2. bundled known_games display name
        #   3. fall back to the raw product_id
        if config is not None and config.display_name:
            title_text = config.display_name
        elif known is not None:
            title_text = known.display_name
        else:
            title_text = self._installed.product_id

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # --- top row: icon + title + settings ---
        top = QHBoxLayout()
        top.setSpacing(10)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(32, 32)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._set_icon(config.exe_path if config is not None else None)
        top.addWidget(self._icon_label)

        self._title = QLabel(f"<b>{title_text}</b>")
        self._title.setWordWrap(True)
        self._title.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        top.addWidget(self._title, stretch=1)

        self._settings_btn = QPushButton()
        self._settings_btn.setIcon(
            QIcon(render_icon("settings", 18, self._tokens.state_setup))
        )
        self._settings_btn.setIconSize(QSize(18, 18))
        self._settings_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 4px; }"
        )
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setToolTip(t("card.settings_tooltip"))
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.installEventFilter(self)
        self._settings_btn.clicked.connect(
            lambda: self.settings_clicked.emit(self._installed.product_id)
        )
        top.addWidget(self._settings_btn)
        root.addLayout(top)

        # --- middle: profile dropdown ---
        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)
        profile_label = QLabel(t("card.profile_label"))
        profile_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        profile_row.addWidget(profile_label)

        self._profile_combo = QComboBox()
        self._populate_profile_combo(profiles, config, default_profile)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self._profile_combo.installEventFilter(self)
        profile_row.addWidget(self._profile_combo, stretch=1)
        root.addLayout(profile_row)

        root.addStretch(1)

        # --- bottom-left: status caption ---
        self._status_label = QLabel(_state_label(self._state))
        font = QFont()
        font.setBold(True)
        font.setPointSize(font.pointSize())
        self._status_label.setFont(font)
        self._status_label.setStyleSheet(
            f"color: {_state_text_color(self._state, self._tokens)};"
        )
        self._status_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        root.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignLeft)

    # --- icon ---

    def _set_icon(self, exe_path: Path | None) -> None:
        icon = get_exe_icon(exe_path)
        if icon is not None and not icon.isNull():
            pix = icon.pixmap(QSize(32, 32))
            if not pix.isNull():
                self._icon_label.setPixmap(pix)
                return
        # Fallback: bundled "apps" Fluent icon, recolored to match the
        # current theme's placeholder hue.
        self._icon_label.setPixmap(
            render_icon("apps", 28, self._tokens.icon_placeholder)
        )

    # --- profile dropdown ---

    def _populate_profile_combo(
        self,
        profiles: list[Profile],
        config: GameConfig | None,
        default_profile: Profile | None,
    ) -> None:
        default_label = (
            t("card.profile.default", name=default_profile.name)
            if default_profile is not None
            else t("card.profile.default_empty")
        )
        self._profile_combo.addItem(default_label, None)
        for p in profiles:
            label = p.name + (f" <{p.email}>" if p.email else "")
            self._profile_combo.addItem(label, p.id)

        target_id = config.profile_id if config is not None else None
        for i in range(self._profile_combo.count()):
            if self._profile_combo.itemData(i) == target_id:
                self._profile_combo.setCurrentIndex(i)
                break

    def _on_profile_changed(self, _index: int) -> None:
        data = self._profile_combo.currentData()
        profile_id: str | None = str(data) if data else None
        self.profile_changed.emit(self._installed.product_id, profile_id)

    # --- hover animation + paint ---

    def _animate_to(self, target: float) -> None:
        if self._state is CardState.RUNNING:
            return
        self._anim.stop()
        self._anim.setStartValue(self._hover_t)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event: object) -> None:
        if not self._child_hovered:
            self._animate_to(1.0)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: QEvent | None) -> None:
        self._animate_to(0.0)
        super().leaveEvent(event)

    # --- per-child hover animations ---

    def _wire_child_hover_effects(self) -> None:
        """Attach a colorize effect + property animation to the dropdown
        and the settings button.

        ``QGraphicsColorizeEffect.strength`` is a Qt property, so we can
        drive it with ``QPropertyAnimation`` and an easing curve directly
        — no need to repaint stylesheets each frame. Strength is animated
        between 0 (no tint) and a per-widget cap.
        """
        accent_color = QColor(self._tokens.accent)

        self._settings_effect = QGraphicsColorizeEffect(self._settings_btn)
        self._settings_effect.setColor(accent_color)
        self._settings_effect.setStrength(0.0)
        self._settings_btn.setGraphicsEffect(self._settings_effect)
        self._settings_anim = QPropertyAnimation(
            self._settings_effect, b"strength", self
        )
        self._settings_anim.setDuration(CHILD_HOVER_DURATION_MS)
        self._settings_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._combo_effect = QGraphicsColorizeEffect(self._profile_combo)
        self._combo_effect.setColor(accent_color)
        self._combo_effect.setStrength(0.0)
        self._profile_combo.setGraphicsEffect(self._combo_effect)
        self._combo_anim = QPropertyAnimation(
            self._combo_effect, b"strength", self
        )
        self._combo_anim.setDuration(CHILD_HOVER_DURATION_MS)
        self._combo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _animate_child(
        self, anim: QPropertyAnimation, effect: QGraphicsColorizeEffect, target: float
    ) -> None:
        anim.stop()
        anim.setStartValue(effect.strength())
        anim.setEndValue(target)
        anim.start()

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        # Be defensive — Qt can dispatch through eventFilter during widget
        # construction (before ``_build_ui`` finishes wiring the children).
        combo = getattr(self, "_profile_combo", None)
        settings = getattr(self, "_settings_btn", None)
        if event is not None and (obj is combo or obj is settings):
            etype = event.type()
            if etype == QEvent.Type.Enter:
                self._child_hovered = True
                # Card returns to idle so the user's focus is on the child.
                self._animate_to(0.0)
                if obj is settings and hasattr(self, "_settings_anim"):
                    self._animate_child(
                        self._settings_anim,
                        self._settings_effect,
                        SETTINGS_HOVER_STRENGTH,
                    )
                elif obj is combo and hasattr(self, "_combo_anim"):
                    self._animate_child(
                        self._combo_anim,
                        self._combo_effect,
                        COMBO_HOVER_STRENGTH,
                    )
            elif etype == QEvent.Type.Leave:
                self._child_hovered = False
                if obj is settings and hasattr(self, "_settings_anim"):
                    self._animate_child(
                        self._settings_anim, self._settings_effect, 0.0
                    )
                elif obj is combo and hasattr(self, "_combo_anim"):
                    self._animate_child(
                        self._combo_anim, self._combo_effect, 0.0
                    )
                if self.underMouse() and self._state is not CardState.RUNNING:
                    self._animate_to(1.0)
        return super().eventFilter(obj, event)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = _blend_hex(
            self._tokens.surface,
            _hover_color(self._state, self._tokens),
            self._hover_t,
        )
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor(bg))
        painter.setPen(QPen(QColor(self._tokens.surface_border), 1))
        painter.drawRoundedRect(rect, 8, 8)
        painter.end()

    # --- click ---

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        should_emit = (
            event.button() == Qt.MouseButton.LeftButton
            and self._press_pos is not None
            and self.rect().contains(event.pos())
            and self._state is not CardState.RUNNING
        )
        # Snapshot the product_id BEFORE the emit — the slot for
        # ``status_clicked`` can open a modal dialog (ProgressDialog),
        # whose nested event loop processes ``deleteLater`` for this
        # card via ``MainWindow.refresh`` rebuilding the grid. After
        # that point the C++ widget is gone and any ``self.*`` access
        # raises ``wrapped C/C++ object has been deleted``.
        product_id = self._installed.product_id if should_emit else None
        self._press_pos = None
        # Run super() while we're still alive — it touches the C++
        # widget and would crash if called after the emit.
        super().mouseReleaseEvent(event)
        if product_id is not None:
            self.status_clicked.emit(product_id)
        # Do NOT touch ``self`` after this point.
