"""Profile management dialog.

Per the spec discussion, this is built for non-developers:

- Terminology: "토큰" → "계정". "토큰 발급" → "계정 설정".
- A profile that has a token is treated as logged in. A profile without
  a token shows an orange "[재로그인 필요]" badge — that's the only
  badge we render. The "good" state has no badge so the row stays calm.
- "마지막 사용" is right-aligned and dimmed (using the system palette so
  dark and light themes both render it readable).
- "(기본)" prefix marks the default profile.

Action surface:

- Add / Delete: top-right toolbar (frequent identity-shaping actions).
- 이름 변경 / 기본으로 설정 / 로그아웃: bottom row (per-profile actions).
- *Login is no longer triggered from this dialog* — by design, the user
  triggers a login by clicking the game card on the main screen for
  whichever game is bound to that profile. This avoids duplicate entry
  points and keeps the flow oriented around "I want to play X" rather
  than "I should manage my tokens."
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PyQt6.QtCore import QModelIndex, QSize, Qt
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.api import DmmApiClient
from shantytown.core.i18n import t
from shantytown.store.profiles import Profile, ProfileStore
from shantytown.store.settings import LoginMethod, SettingsStore

from .toggle_switch import ToggleSwitch
from .webview_support import webview_available

# Amber works on both light and dark themes — keep fixed for branding.
_BADGE_NEEDS_LOGIN_HEX = "#f59e0b"
# Blue for the email — a mid-tone that stays readable on light and dark.
_EMAIL_HEX = "#4a90d9"

# Shared geometry across all dialog buttons so colored and palette-default
# buttons line up on the same baseline.
_BUTTON_GEOMETRY = (
    "border-radius: 4px; padding: 6px 14px; font-weight: 500; min-height: 18px;"
)

# Neutral (palette-driven) — same geometry as the colored ones so heights
# match. The OS theme owns the actual colors via palette(...) refs.
_NEUTRAL_BUTTON = (
    "QPushButton { background-color: palette(button); color: palette(button-text); "
    "border: 1px solid palette(mid); "
    + _BUTTON_GEOMETRY
    + " }"
    "QPushButton:hover:!disabled { background-color: palette(midlight); }"
    "QPushButton:disabled { color: palette(placeholder-text); }"
)

# Primary (muted blue) — used for the "Add" action since creating a
# profile is the only thing the user can do when the list is empty.
# Lower saturation than tailwind blue-600 for a calmer feel.
_PRIMARY_BUTTON = (
    "QPushButton { background-color: #4a73c2; color: white; border: none; "
    + _BUTTON_GEOMETRY
    + " }"
    "QPushButton:hover:!disabled { background-color: #3a5fa2; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
)

# Danger (muted red) — for destructive actions: delete profile, logout.
# Same desaturated treatment as the primary so the two read as a pair
# rather than a stoplight.
_DANGER_BUTTON = (
    "QPushButton { background-color: #c25555; color: white; border: none; "
    + _BUTTON_GEOMETRY
    + " }"
    "QPushButton:hover:!disabled { background-color: #a44545; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
)

_TOOLBAR_BUTTON_WIDTH = 88


def _humanize_dt(when: datetime | None) -> str:
    if when is None:
        return t("profile.never_used_dash")
    return when.strftime("%Y-%m-%d %H:%M")


def needs_relogin(profile: Profile) -> bool:
    """Whether to show the orange [재로그인 필요] badge.

    Today the rule is "no token stored" — token-expiry detection lands
    later when we wire up TokenCheckWorker on dialog open.
    """
    return not profile.token


def format_profile_html(
    profile: Profile,
    is_default: bool,
    *,
    last_used_color: str = "#9ca3af",
) -> str:
    """Build the HTML rendered into each list row.

    Args:
        last_used_color: Hex color for the right-aligned "마지막 사용"
            text. Callers should derive this from the system palette
            (``palette.placeholderText().color()``) so the row stays
            readable on both light and dark themes.
    """
    parts: list[str] = []
    if is_default:
        parts.append(f"<b>{t('profile.default_marker')}</b>")
    name_html = profile.name
    if profile.email:
        name_html = (
            f"{name_html} "
            f"<span style='color:{_EMAIL_HEX};'>&lt;{profile.email}&gt;</span>"
        )
    parts.append(name_html)
    if needs_relogin(profile):
        parts.append(
            f"<span style='color:{_BADGE_NEEDS_LOGIN_HEX}; font-weight:600;'>"
            f"{t('profile.relogin_badge')}</span>"
        )
    left = " ".join(parts)
    right = (
        f"<span style='color:{last_used_color};'>"
        f"{t('profile.last_used', date=_humanize_dt(profile.last_used_at))}"
        "</span>"
    )
    return (
        "<table width='100%' style='border-collapse:collapse;'><tr>"
        f"<td>{left}</td>"
        f"<td align='right'>{right}</td>"
        "</tr></table>"
    )


class _HtmlDelegate(QStyledItemDelegate):
    """Renders rows as HTML so we can embed colored spans + alignment.

    Selection background uses ``palette.highlight()`` so the highlight
    color follows the system theme (no more pinning a light-blue value
    that would clash on dark mode).
    """

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        from PyQt6.QtGui import QTextDocument

        if painter is None:
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        painter.save()
        if opt.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(opt.rect, opt.palette.highlight())
        doc = QTextDocument()
        doc.setHtml(opt.text)
        opt.text = ""
        painter.translate(opt.rect.left() + 6, opt.rect.top() + 4)
        doc.setTextWidth(opt.rect.width() - 12)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QSize:
        return QSize(option.rect.width(), 32)


class ProfileDialog(QDialog):
    """CRUD UI over a ``ProfileStore``."""

    def __init__(
        self,
        store: ProfileStore,
        api: DmmApiClient,
        parent: QWidget | None = None,
        *,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._api = api
        self._settings_store = settings_store
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        self.setWindowTitle(t("profile.title"))
        self.resize(620, 420)
        root = QVBoxLayout(self)

        # --- top toolbar: title left, add/delete right ---
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(f"<b>{t('profile.heading')}</b>"))
        toolbar.addStretch(1)

        # Webview-login on/off switch. Shown only when a settings store is
        # wired in AND the webview login helper (__loginhelper) is actually
        # available — a browser-only install (no helper) hides it. Sits to
        # the left of the Add button (on = webview, off = browser).
        self._login_method_row = QWidget()
        method_layout = QHBoxLayout(self._login_method_row)
        method_layout.setContentsMargins(0, 0, 8, 0)
        method_layout.setSpacing(6)

        # Auto-login on/off — sits to the LEFT of the webview switch and is
        # only meaningful (and only shown) while webview login is on. When
        # on: saved-credential logins submit without a click, and expired
        # tokens auto re-authenticate (see main_window).
        self._auto_login_widget = QWidget()
        auto_layout = QHBoxLayout(self._auto_login_widget)
        auto_layout.setContentsMargins(0, 0, 8, 0)
        auto_layout.setSpacing(6)
        auto_label = QLabel(t("profile.auto_login_label"))
        self._auto_login_switch = ToggleSwitch()
        self._auto_login_switch.setToolTip(t("profile.auto_login.tooltip"))
        self._auto_login_switch.setChecked(self._current_auto_login())
        self._auto_login_switch.toggled.connect(self._on_auto_login_toggled)
        auto_layout.addWidget(auto_label)
        auto_layout.addWidget(self._auto_login_switch)
        method_layout.addWidget(self._auto_login_widget)

        method_label = QLabel(t("profile.webview_toggle_label"))
        self._login_method_switch = ToggleSwitch()
        self._login_method_switch.setToolTip(t("profile.webview_toggle.tooltip"))
        webview_on = self._current_login_method() == "webview"
        self._login_method_switch.setChecked(webview_on)
        self._login_method_switch.toggled.connect(self._on_login_method_toggled)
        method_layout.addWidget(method_label)
        method_layout.addWidget(self._login_method_switch)
        # Auto-login is a sub-option of webview login → hidden unless on.
        self._auto_login_widget.setVisible(webview_on)
        self._login_method_row.setVisible(
            self._settings_store is not None and webview_available()
        )
        toolbar.addWidget(self._login_method_row)

        self._add_btn = QPushButton(t("profile.add_button"))
        self._add_btn.setStyleSheet(_PRIMARY_BUTTON)
        self._add_btn.setFixedWidth(_TOOLBAR_BUTTON_WIDTH)
        self._add_btn.clicked.connect(self._add_profile)
        toolbar.addWidget(self._add_btn)

        self._delete_btn = QPushButton(t("profile.delete_button"))
        self._delete_btn.setStyleSheet(_DANGER_BUTTON)
        self._delete_btn.setFixedWidth(_TOOLBAR_BUTTON_WIDTH)
        self._delete_btn.clicked.connect(self._delete_profile)
        toolbar.addWidget(self._delete_btn)

        root.addLayout(toolbar)

        # --- list ---
        self._list = QListWidget()
        self._list.setItemDelegate(_HtmlDelegate(self._list))
        self._list.currentItemChanged.connect(self._on_selection_changed)
        root.addWidget(self._list, stretch=1)

        # --- bottom row: per-profile actions + close ---
        action_row = QHBoxLayout()
        self._rename_btn = QPushButton(t("profile.rename_button"))
        self._rename_btn.setStyleSheet(_NEUTRAL_BUTTON)
        self._default_btn = QPushButton(t("profile.default_button"))
        self._default_btn.setStyleSheet(_NEUTRAL_BUTTON)
        self._logout_btn = QPushButton(t("profile.logout_button"))
        self._logout_btn.setStyleSheet(_DANGER_BUTTON)
        for b, slot in [
            (self._rename_btn, self._rename_profile),
            (self._default_btn, self._set_default),
            (self._logout_btn, self._logout),
        ]:
            b.clicked.connect(slot)
            action_row.addWidget(b)
        action_row.addStretch(1)
        self._close_btn = QPushButton(t("profile.close_button"))
        self._close_btn.setStyleSheet(_NEUTRAL_BUTTON)
        self._close_btn.clicked.connect(self.accept)
        action_row.addWidget(self._close_btn)
        root.addLayout(action_row)

        # Selection-dependent buttons start disabled — the list is empty
        # on first open or has nothing focused yet.
        self._update_selection_state(has_selection=False)

    # --- helpers ---

    def _update_selection_state(self, *, has_selection: bool) -> None:
        """Toggle selection-dependent buttons. Add/Close stay always enabled."""
        for b in (self._rename_btn, self._default_btn, self._logout_btn, self._delete_btn):
            b.setEnabled(has_selection)

    def _on_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self._update_selection_state(has_selection=current is not None)

    def _last_used_color(self) -> str:
        """Pull the placeholder-text color from the current palette."""
        return self.palette().color(QPalette.ColorRole.PlaceholderText).name()

    def _refresh(self) -> None:
        self._list.clear()
        default = self._store.get_default()
        default_id = default.id if default else None
        last_used_color = self._last_used_color()
        for p in self._store.list():
            item = QListWidgetItem(
                format_profile_html(
                    p,
                    p.id == default_id,
                    last_used_color=last_used_color,
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self._list.addItem(item)
        # ``clear`` drops any prior selection — sync button state.
        self._update_selection_state(has_selection=False)

    def _selected_profile(self) -> Profile | None:
        item = self._list.currentItem()
        if item is None:
            return None
        pid = item.data(Qt.ItemDataRole.UserRole)
        return self._store.get(str(pid))

    # --- login method toggle ---

    def _current_login_method(self) -> LoginMethod:
        if self._settings_store is None:
            return "browser"
        return self._settings_store.get().login_method

    def _on_login_method_toggled(self, checked: bool) -> None:
        if self._settings_store is None:
            return
        next_method: LoginMethod = "webview" if checked else "browser"
        current = self._settings_store.get()
        self._settings_store.update(replace(current, login_method=next_method))
        # Auto-login only applies to webview; reveal/hide it with the switch.
        self._auto_login_widget.setVisible(checked)

    def _current_auto_login(self) -> bool:
        if self._settings_store is None:
            return False
        return self._settings_store.get().auto_login

    def _on_auto_login_toggled(self, checked: bool) -> None:
        if self._settings_store is None:
            return
        current = self._settings_store.get()
        self._settings_store.update(replace(current, auto_login=checked))

    # --- actions ---

    def _add_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, t("profile.add.title"), t("profile.add.prompt")
        )
        if not ok or not name.strip():
            return
        self._store.create(name.strip())
        self._refresh()

    def _rename_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        new_name, ok = QInputDialog.getText(
            self, t("profile.rename.title"), t("profile.rename.prompt"), text=profile.name
        )
        if not ok or not new_name.strip():
            return
        renamed = Profile(
            id=profile.id,
            name=new_name.strip(),
            token=profile.token,
            created_at=profile.created_at,
            last_used_at=profile.last_used_at,
            email=profile.email,
            password=profile.password,
        )
        self._store.update(renamed)
        self._refresh()

    def _delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if (
            QMessageBox.question(
                self,
                t("profile.delete.title"),
                t("profile.delete.body", name=profile.name),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._store.delete(profile.id)
        self._refresh()

    def _set_default(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self._store.set_default(profile.id)
        self._refresh()

    def _logout(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not profile.token:
            QMessageBox.information(
                self,
                t("profile.already_logout.title"),
                t("profile.already_logout.body"),
            )
            return
        if (
            QMessageBox.question(
                self,
                t("profile.logout.title"),
                t("profile.logout.body", name=profile.name),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._store.update(
            Profile(
                id=profile.id,
                name=profile.name,
                token=None,
                created_at=profile.created_at,
                last_used_at=profile.last_used_at,
                email=profile.email,
                password=profile.password,
            )
        )
        self._refresh()
