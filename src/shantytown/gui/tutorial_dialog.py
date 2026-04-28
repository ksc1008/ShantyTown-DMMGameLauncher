"""First-run tutorial.

Five-page walkthrough that explains the DMM-Launcher prerequisite,
profiles, the auto-detected library, how to launch with a chosen
profile, and how the browser sign-in step works. Lives in its own
dialog so the help (?) button on the main window can replay it on
demand.

Layout per page:

    ┌──────────────────────────────────────┐
    │                                      │
    │            [image, sharp]            │
    │                                      │
    │  Page title (bold, larger)           │
    │  Body text, word-wrapped.            │
    ├──────────────────────────────────────┤
    │ ● ○ ○ ○ ○      [Skip]   [Back] [Next]│
    └──────────────────────────────────────┘

Image rendering: source PNGs (often >1000px wide) are scaled with
``Qt.SmoothTransformation`` at the device-pixel ratio of the target
screen so the image stays crisp on HiDPI displays — using a plain
``QPixmap.scaled`` with the logical size produced visibly soft results
on 1.5x / 2x scales.

Page transitions: the pages share an inner container that's wider than
the dialog; switching between pages animates the container's ``pos.x``
with an OutCubic easing curve. Qt clips children to the parent rect,
so off-screen pages don't paint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PyQt6.QtGui import QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from shantytown.core.i18n import t

from .fluent import current_tokens

_TUTORIAL_DIR: Path = (
    Path(__file__).resolve().parents[1] / "resources" / "tutorial"
)
# Image area uses the full dialog content width. The 16:9 height
# follows naturally since the source PNGs are 16:9 — KeepAspectRatio
# does the right thing if a source comes in slightly off.
_IMAGE_TARGET = QSize(780, 440)

# Page-level layout constants. Picked so the slide stack is sized to
# *exactly* the content height — no leftover vertical space below the
# body. The dialog is in turn fixed to ``stack + footer + margins``,
# also without any "absorb leftover" stretch.
_TITLE_FONT_BUMP = 6  # points added to default font for the page title
_BODY_FONT_BUMP = 1
_GAP_IMAGE_TO_TITLE = 28
_GAP_TITLE_TO_BODY = 8
_TITLE_RESERVED_HEIGHT = 36  # bold +6pt fits comfortably in ~30
_BODY_RESERVED_HEIGHT = 84  # up to 3 wrapped lines at +1pt
_STACK_CONTENT_HEIGHT = (
    _IMAGE_TARGET.height()
    + _GAP_IMAGE_TO_TITLE
    + _TITLE_RESERVED_HEIGHT
    + _GAP_TITLE_TO_BODY
    + _BODY_RESERVED_HEIGHT
)
# Dialog vertical breakdown:
#   20 (top margin) + stack + 16 (root spacing) + ~40 (footer) + 16 (bottom)
_DIALOG_DEFAULT_SIZE = QSize(820, _STACK_CONTENT_HEIGHT + 92)
_SLIDE_DURATION_MS = 280

_PRIMARY_BUTTON = (
    "QPushButton { background-color: #4a73c2; color: white; border: none; "
    "border-radius: 4px; padding: 6px 18px; font-weight: 600; min-height: 22px; }"
    "QPushButton:hover:!disabled { background-color: #3a5fa2; }"
    "QPushButton:disabled { background-color: palette(mid); color: palette(placeholder-text); }"
)


@dataclass(frozen=True)
class _Page:
    image: str
    title_key: str
    body_key: str


_PAGES: tuple[_Page, ...] = (
    _Page(
        "tutorial_01_dmm_launcher.png", "tutorial.page1.title", "tutorial.page1.body"
    ),
    _Page("tutorial_02_profiles.png", "tutorial.page2.title", "tutorial.page2.body"),
    _Page("tutorial_03_main_grid.png", "tutorial.page3.title", "tutorial.page3.body"),
    _Page("tutorial_04_launch.png", "tutorial.page4.title", "tutorial.page4.body"),
    _Page("tutorial_05_login.png", "tutorial.page5.title", "tutorial.page5.body"),
)


def _scaled_pixmap(path: Path, target: QSize, device_pixel_ratio: float) -> QPixmap:
    """Render ``path`` to ``target`` at the screen's device pixel ratio.

    Without DPR awareness, scaled QPixmaps look soft on HiDPI screens
    because Qt up-samples a low-res pixmap to fit the logical size. We
    scale the source to the *physical* target size and then tell Qt the
    pixmap is HiDPI so it composes back to the right logical bounds.
    """
    pix = QPixmap(str(path))
    if pix.isNull():
        return pix
    physical = QSize(
        max(1, int(target.width() * device_pixel_ratio)),
        max(1, int(target.height() * device_pixel_ratio)),
    )
    scaled = pix.scaled(
        physical,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(device_pixel_ratio)
    return scaled


class _TutorialPage(QWidget):
    """One page of the walkthrough — image, title, body."""

    def __init__(self, page: _Page, dpr: float) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setFixedHeight(_IMAGE_TARGET.height())
        image_path = _TUTORIAL_DIR / page.image
        if image_path.is_file():
            self._image_label.setPixmap(
                _scaled_pixmap(image_path, _IMAGE_TARGET, dpr)
            )
        layout.addWidget(self._image_label)

        # Image → title gap.
        layout.addSpacing(_GAP_IMAGE_TO_TITLE)

        title = QLabel(t(page.title_key))
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + _TITLE_FONT_BUMP)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setFixedHeight(_TITLE_RESERVED_HEIGHT)
        layout.addWidget(title)

        # Title → body gap.
        layout.addSpacing(_GAP_TITLE_TO_BODY)

        body = QLabel(t(page.body_key))
        body_font = body.font()
        body_font.setPointSize(body_font.pointSize() + _BODY_FONT_BUMP)
        body.setFont(body_font)
        body.setWordWrap(True)
        body.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        body.setFixedHeight(_BODY_RESERVED_HEIGHT)
        layout.addWidget(body)
        # No trailing stretch — the page is exactly the sum of its
        # children. The slide stack matches this height, so there's no
        # leftover vertical area below the body.


class _SlideStack(QWidget):
    """Horizontal page container with animated transitions.

    Pages live side-by-side inside a single ``_inner`` widget; we
    animate ``_inner``'s x position to scroll between them. Qt clips
    children to the parent rect, so off-screen pages don't bleed
    visually outside this widget.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pages: list[QWidget] = []
        self._current_index = 0
        self._anim: QPropertyAnimation | None = None
        self._inner = QWidget(self)
        self._inner.move(0, 0)

    def add_page(self, page: QWidget) -> None:
        page.setParent(self._inner)
        idx = len(self._pages)
        page.setGeometry(idx * self.width(), 0, self.width(), self.height())
        self._pages.append(page)
        page.show()
        self._size_inner()

    def current_index(self) -> int:
        return self._current_index

    def page_count(self) -> int:
        return len(self._pages)

    def go_to(self, index: int) -> None:
        if index == self._current_index or not (0 <= index < len(self._pages)):
            return
        target_x = -index * self.width()
        if self._anim is not None and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._anim = QPropertyAnimation(self._inner, b"pos", self)
        self._anim.setDuration(_SLIDE_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._inner.pos())
        self._anim.setEndValue(QPoint(target_x, 0))
        self._anim.start()
        self._current_index = index

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        # Re-pack pages and snap to the current page's offset (no animation).
        for i, page in enumerate(self._pages):
            page.setGeometry(i * self.width(), 0, self.width(), self.height())
        self._size_inner()
        self._inner.move(-self._current_index * self.width(), 0)

    def _size_inner(self) -> None:
        self._inner.resize(max(1, self.width() * len(self._pages)), self.height())


class _DotIndicator(QFrame):
    """Row of small circles showing the current page position."""

    DOT_SIZE = 9
    SPACING = 6

    def __init__(self, count: int) -> None:
        super().__init__()
        self._dots: list[QLabel] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.SPACING)
        for _ in range(count):
            dot = QLabel()
            dot.setFixedSize(self.DOT_SIZE, self.DOT_SIZE)
            self._dots.append(dot)
            layout.addWidget(dot)

    def set_active(self, index: int) -> None:
        for i, dot in enumerate(self._dots):
            if i == index:
                dot.setStyleSheet(
                    f"background-color: palette(highlight); "
                    f"border-radius: {self.DOT_SIZE // 2}px;"
                )
            else:
                dot.setStyleSheet(
                    f"background-color: transparent; "
                    f"border: 1px solid palette(mid); "
                    f"border-radius: {self.DOT_SIZE // 2}px;"
                )


class TutorialDialog(QDialog):
    """First-run walkthrough. Modal, reopen-able from the help button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("tutorial.title"))
        self.setModal(True)
        self.setFixedSize(_DIALOG_DEFAULT_SIZE)
        self._tokens = current_tokens(self)

        # Pixmaps are rendered at the parent's DPR so they stay crisp
        # on HiDPI screens without forcing every monitor to use 1x.
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(16)

        self._stack = _SlideStack()
        # Lock the stack to the exact content height so no leftover
        # space appears below the body text.
        self._stack.setFixedHeight(_STACK_CONTENT_HEIGHT)
        for page in _PAGES:
            self._stack.add_page(_TutorialPage(page, dpr))
        root.addWidget(self._stack)

        # --- footer: dots left, buttons right ---
        footer = QHBoxLayout()
        self._dots = _DotIndicator(len(_PAGES))
        footer.addWidget(self._dots, alignment=Qt.AlignmentFlag.AlignVCenter)
        footer.addStretch(1)

        self._skip_btn = QPushButton(t("tutorial.skip"))
        self._skip_btn.clicked.connect(self.accept)
        footer.addWidget(self._skip_btn)

        self._back_btn = QPushButton(t("tutorial.back"))
        self._back_btn.clicked.connect(self._on_back)
        footer.addWidget(self._back_btn)

        self._next_btn = QPushButton()
        self._next_btn.setStyleSheet(_PRIMARY_BUTTON)
        self._next_btn.clicked.connect(self._on_next)
        footer.addWidget(self._next_btn)

        root.addLayout(footer)

        self._sync_buttons()

    # --- navigation ---

    def _on_next(self) -> None:
        idx = self._stack.current_index()
        if idx >= self._stack.page_count() - 1:
            self.accept()
            return
        self._stack.go_to(idx + 1)
        self._sync_buttons()

    def _on_back(self) -> None:
        idx = self._stack.current_index()
        if idx <= 0:
            return
        self._stack.go_to(idx - 1)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        idx = self._stack.current_index()
        last = idx == self._stack.page_count() - 1
        first = idx == 0
        self._dots.set_active(idx)
        self._back_btn.setEnabled(not first)
        self._back_btn.setVisible(not first)
        self._skip_btn.setVisible(not last)
        self._next_btn.setText(
            t("tutorial.finish") if last else t("tutorial.next")
        )
