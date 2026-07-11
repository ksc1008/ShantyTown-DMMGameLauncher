# Shantytown (판자촌)

[한국어](../README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

A PyQt6 alternative launcher for DMM Game Player. Lets you assign a different DMM account (a "profile") to each installed game.  
Already-installed DMM games can be launched from outside Japan without a VPN.

## Features

- Per-profile DMM account isolation
- Auto-detects installed games by parsing `dmmgame.cnf`
- API calls work from non-Japan IPs
- Two sign-in methods
  - External-browser sign-in with automatic clipboard pickup
  - In-app sign-in (webview) — log in to DMM inside the app, no browser needed
- Auto-login (webview method): sign in with saved credentials without a click, and re-authenticate automatically when the token expires
- Tokens and account details (email / password) stored encrypted via DPAPI (Windows only)
- Per-game desktop shortcuts (shortcuts still go through the full auth + launch flow)
- Light / dark / system themes; Korean / English UI
- Single-file exe distribution (webview sign-in only works when the `__loginhelper.exe` companion is present)

## How to use

Download the latest release from the Releases tab and run it. To use in-app sign-in (webview), keep `shantytown.exe` and `__loginhelper.exe` together in the same folder. With `shantytown.exe` alone, only browser sign-in is available.

Games must be installed through the official DMM Game Player first. This app only handles launching already-installed games.

## Tutorial

Same content as the in-app first-run guide.

| Step | Screen |
| --- | --- |
| 1. Install games | <img src="../src/shantytown/resources/tutorial/tutorial_01_dmm_launcher.png" width="400"> |
| 2. Create profiles | <img src="../src/shantytown/resources/tutorial/tutorial_02_profiles.png" width="400"> |
| 3. Game library | <img src="../src/shantytown/resources/tutorial/tutorial_03_main_grid.png" width="400"> |
| 4. Launch | <img src="../src/shantytown/resources/tutorial/tutorial_04_launch.png" width="400"> |
| 5. DMM sign-in | <img src="../src/shantytown/resources/tutorial/tutorial_05_login.png" width="400"> |

1. Install the games you want through DMM Game Player. (A VPN may be needed during download.)
2. Create one profile per DMM account you'll use.
3. Games installed on this PC appear on the main screen automatically.
4. Click a game card to launch. Switching profiles plays the same game with a different DMM account.
5. The first time you launch with a profile (or after the token expires), sign in to DMM. Choose the external-browser method or the in-app (webview) method in the profile manager; enable auto-login to sign in with saved credentials automatically. (A VPN may be needed during sign-in.)

---
## Development setup

Python 3.11+, [`uv`](https://docs.astral.sh/uv/) recommended.

```bash
git clone <repo-url>
cd shantytown
uv sync
uv run python -m shantytown
```

## Tests / type-check / lint

```bash
uv run pytest -v
uv run mypy src/
uv run ruff check src/ tests/
```

## Build the exe

```bash
uv sync
uv run python scripts/build_exe.py            # both exes (main + helper)
# or: .\build.ps1
# → dist/shantytown.exe, dist/__loginhelper.exe
```

The build produces two exes:

- `shantytown.exe` — the app. Renders `app_icon.svg` into a multi-resolution `.ico` and runs PyInstaller in `--onefile --windowed` mode, with QtWebEngine excluded for a fast startup (around 42 MB, self-contained).
- `__loginhelper.exe` — the in-app (webview) sign-in engine: a console app bundling QtWebEngine, spawned by the app only when needed.

Use `--target main` / `--target helper` to build just one. Ship the two together in one folder; distributing `shantytown.exe` alone makes it browser-sign-in only.

## CLI flags

| Flag | Effect |
| --- | --- |
| `--debug` | Show full error responses; enables the telemetry hook. |
| `--locale=ko` / `--locale=en` | Force UI language. Defaults to system locale. |
| `--show-tutorial` | Force the first-run walkthrough on this launch. (Does not flip the saved flag.) |
| `--show-webview` | Show the webview sign-in window on screen. A debug aid for clearing reCAPTCHA / 2FA by hand. |
| `--launch=<product_id>` | Launch the given game directly. Used by the desktop shortcuts. |

Other flags are passed through to Qt (e.g. `-platform offscreen`).

## Project layout

```
src/shantytown/
  core/        # Qt-free pure logic: API client, MD5 verify, downloader,
               #  DPAPI wrapper, telemetry, locale detection, login-page parsing
  store/       # JSON-backed persistence: profiles / game configs / app
               #  settings / known_games
  gui/         # PyQt6 surface: main window, cards, dialogs (browser & webview
               #  sign-in, profile, game settings, tutorial, progress), workers, theme
  loginhelper.py  # Entry point for the webview sign-in helper process (__loginhelper.exe)
  resources/   # Bundled assets: Fluent UI icons, tutorial PNGs, app icon SVG
tests/         # ~360 tests
scripts/       # build_exe.py (builds the main / helper exes)
docs/          # Original PowerShell prototype and sprint plans
```

## Caveats

- This app launches games through unofficial channels. Use at your own risk.

---

The full source — and this README — were written with [Claude Code](https://claude.com/claude-code).  
Starting from a single 466-line PowerShell prototype, the entire app (GUI / i18n / DPAPI / exe build / 165 tests) was built in one chat session. The human side was mostly feedback like "this color is off", "it's crashing here", "let's go to the next sprint".
