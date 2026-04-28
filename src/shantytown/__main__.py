"""Entry point for ``python -m shantytown``.

Wires the persistent stores, the DMM API client, and the main window
together. Applies the saved theme before showing the window so we
don't flash with the default palette on first paint. On first run (no
profiles yet) we open the profile dialog proactively so the user has
somewhere to start.

The CLI accepts a single optional flag, ``--debug``. When passed:

- ``SHANTYTOWN_DEBUG=1`` is set so ``shantytown.core.debug.is_debug()``
  returns True for any code that wants verbose error reporting.
- ``SHANTYTOWN_TELEMETRY=1`` is set, enabling the telemetry hook in
  ``shantytown.core.telemetry``. Actual sending still requires the
  user to configure ``SHANTYTOWN_TELEMETRY_ENDPOINT`` separately.
"""

from __future__ import annotations

import argparse
import os
import sys


def _parse_args(argv: list[str]) -> tuple[bool, str | None, bool, list[str]]:
    """Pull our flags out of ``argv`` so QApplication never sees them.

    Returns ``(debug_flag, locale_override, show_tutorial, qt_argv)``.
    We use ``parse_known_args`` so Qt's own command-line flags (e.g.
    ``-platform offscreen`` for tests) pass through untouched.
    """
    parser = argparse.ArgumentParser(prog="shantytown", add_help=False)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--locale", type=str, default=None)
    # Forces the first-run tutorial to show on this launch regardless
    # of the saved ``tutorial_completed`` flag. Useful for re-watching
    # or for QA. The setting is *not* persisted — it's a per-run
    # override, not a reset.
    parser.add_argument("--show-tutorial", action="store_true")
    args, rest = parser.parse_known_args(argv[1:])
    return args.debug, args.locale, args.show_tutorial, [argv[0], *rest]


def main(argv: list[str] | None = None) -> int:
    """Boot the 판자촌 GUI."""
    raw_argv = list(argv if argv is not None else sys.argv)
    debug, locale_override, force_tutorial, qt_argv = _parse_args(raw_argv)

    # Initialise i18n before any string-using code runs. This way both
    # the debug warning below and every QApplication child string sees
    # the active locale.
    from shantytown.core.i18n import init_translator

    init_translator(locale_override)

    if debug:
        os.environ["SHANTYTOWN_DEBUG"] = "1"
        os.environ.setdefault("SHANTYTOWN_TELEMETRY", "1")
        if not os.environ.get("SHANTYTOWN_TELEMETRY_ENDPOINT"):
            sys.stderr.write(
                "[debug] Telemetry flag enabled but no endpoint set — "
                "set SHANTYTOWN_TELEMETRY_ENDPOINT to actually send data.\n"
            )

    from PyQt6.QtWidgets import QApplication

    from shantytown.core.api import DmmApiClient
    from shantytown.core.i18n import t
    from shantytown.gui.main_window import MainWindow
    from shantytown.gui.theme import apply_theme
    from shantytown.gui.tutorial_dialog import TutorialDialog
    from shantytown.store.games import GameStore
    from shantytown.store.paths import (
        get_games_path,
        get_profiles_path,
        get_settings_path,
    )
    from shantytown.store.profiles import ProfileStore
    from shantytown.store.settings import Settings, SettingsStore

    app = QApplication(qt_argv)
    app.setApplicationName(t("app.name"))

    # Pin the app icon for the taskbar / alt-tab. ``MainWindow`` also
    # sets it on the window itself so the title bar gets the bitmap.
    from shantytown.gui.icons import app_icon

    app.setWindowIcon(app_icon())

    # Flatten the default Fusion gradient on buttons/dropdowns so the
    # whole UI reads as Fluent-tone surfaces. Specific widgets can still
    # override (primary/danger buttons in dialogs, the painted cards).
    app.setStyleSheet(
        """
        QPushButton {
            background-color: palette(button);
            color: palette(button-text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            padding: 6px 14px;
            min-height: 18px;
        }
        QPushButton:hover:!disabled {
            background-color: palette(midlight);
        }
        QPushButton:disabled {
            color: palette(placeholder-text);
        }
        QComboBox {
            background-color: palette(button);
            color: palette(button-text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            padding: 4px 8px;
            min-height: 20px;
        }
        QComboBox::drop-down { border: none; width: 18px; }
        QComboBox QAbstractItemView {
            background-color: palette(base);
            color: palette(text);
            border: 1px solid palette(mid);
            selection-background-color: palette(highlight);
            selection-color: palette(highlighted-text);
            outline: 0;
        }
        QLineEdit {
            background-color: palette(base);
            color: palette(text);
            border: 1px solid palette(mid);
            border-radius: 4px;
            padding: 4px 8px;
        }
        QScrollArea { border: none; }
        """
    )

    settings_store = SettingsStore(get_settings_path())
    apply_theme(app, settings_store.get().theme)

    profile_store = ProfileStore(get_profiles_path())
    game_store = GameStore(get_games_path())
    api = DmmApiClient()

    window = MainWindow(
        api=api,
        profile_store=profile_store,
        game_store=game_store,
        settings_store=settings_store,
    )
    window.show()

    # First-run walkthrough. ``--show-tutorial`` is a per-run override
    # that does NOT update the saved flag — useful for replaying the
    # walkthrough without permanently flipping settings.
    saved = settings_store.get()
    if force_tutorial or not saved.tutorial_completed:
        TutorialDialog(parent=window).exec()
        if not force_tutorial:
            settings_store.update(
                Settings(theme=saved.theme, tutorial_completed=True)
            )

    try:
        return app.exec()
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
