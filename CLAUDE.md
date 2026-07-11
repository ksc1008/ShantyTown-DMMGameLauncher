# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

판자촌 (shantytown) — a PyQt6 third-party launcher that wraps DMM Game Player. It lets users run already-installed DMM games under different DMM accounts ("profiles") and from outside Japan without a VPN. It does **not** install games; the official DMM Game Player must install them first. This app only handles authentication + launch of existing installs.

The package name is `shantytown` (import path), distributed as a single Windows exe.

## Commands

Requires Python ≥3.11 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                                    # install deps (incl. dev group)
uv run python -m shantytown                # run the GUI
uv run pytest -v                           # full test suite
uv run pytest tests/test_main_window.py    # single file
uv run pytest tests/test_login_dialog.py::test_extract_code   # single test
uv run mypy src/                           # strict type check (mypy strict mode)
uv run ruff check src/ tests/              # lint (line-length 100; E,F,W,I,B,UP,ANN,RUF)
```

Build the exe (Windows):

```bash
uv run python scripts/build_exe.py    # → dist/shantytown.exe  (~42 MB, self-contained)
# or: .\build.ps1  (thin wrapper: uv sync + build_exe.py + reports size)
```

`build_exe.py` first renders `app_icon.svg` into a multi-resolution `.ico` (build/app_icon.ico), then runs PyInstaller `--onefile --windowed --add-data resources --paths src`.

## Runtime CLI flags

Custom flags are stripped via `argparse.parse_known_args` so remaining args pass through to Qt (e.g. `-platform offscreen` in tests).

- `--debug` — verbose error bodies; sets `SHANTYTOWN_DEBUG=1` and enables the telemetry hook.
- `--locale=ko|en` — force UI language (otherwise system locale is auto-detected).
- `--show-tutorial` — re-run first-run walkthrough this launch without changing the saved flag.
- `--launch=<product_id>` — silent-launch used by generated desktop shortcuts; see launch flow below.

## Architecture

Three-layer separation. `core/` has **no Qt imports** (pure logic: API, OS, crypto). `store/` is JSON persistence. `gui/` is the PyQt6 layer that consumes both as injected dependencies. Everything is wired together in `__main__.py`.

### core/ (Qt-free logic)

- **api.py** — `DmmApiClient` (httpx) against `https://apidgp-gameplayer.games.dmm.com`. Spoofs DMMGamePlayer5-Win/5.4.8 Electron/34.3.0 headers and sends fixed cookies `age_check_done=1; ckcy_remedied_check=ec_mrnhbtk` to bypass region-lock + age-gate. Retries 5xx/network errors 3× with exponential backoff (1/2/4s); 4xx fail immediately. Typed exceptions: `GameNotLinkedError` (3xx — must launch via official client once first), `AuthInvalidError` (203 — token expired).
- **dmmcfg.py** — parses DMM's `%APPDATA%/dmmgameplayer5/dmmgame.cnf` (installed-game registry). **Read-only, single source of truth** for what's installed; never written back.
- **verify.py** — parallel MD5 integrity check (ThreadPoolExecutor, 8 workers) of on-disk files vs the API's file list; reason per file (missing/size/hash/unreadable).
- **download.py** — streaming CDN downloader (signed URL + cookie), atomic temp-swap writes, partial cleanup on failure.
- **hwid.py** — hardware IDs for the launch payload. **Only the MAC is real** (first active NIC); hdd_serial + motherboard are fixed SHA256 dummy values, identical for all users (matches the reference PS1). Breaks if DMM starts validating them.
- **secure_storage.py** — Windows DPAPI via ctypes (`crypt32.dll`). Tokens stored `dpapi:v1:<base64>`; legacy plaintext auto-upgrades on save; decrypt returns `""` on failure (never raises). No-op on non-Windows (plaintext fallback).
- **telemetry.py** — opt-in only (`SHANTYTOWN_TELEMETRY=1` + `SHANTYTOWN_TELEMETRY_ENDPOINT`). Sends relative exe path + product_id; absolute paths stripped; failures swallowed.
- **exe_finder.py** / **process_finder.py** — case-insensitive exe discovery inside a game dir; running-game detection via psutil (path→PID).
- **shortcuts.py** — Windows `.lnk` creation via a PowerShell WScript.Shell COM helper (avoids pywin32). Shortcuts target `shantytown.exe --launch=<product_id>`, **not** the game exe, so every launch goes through the auth/verify flow.
- **i18n.py** — flat KO/EN dicts, fallback chain active→EN→key. `init_translator()` once at startup, global `t()` reads it.
- **models.py** — immutable dataclasses: `FileEntry`, `LaunchResponse`, `InstalledGame`, `HardwareIds`.

### store/ (JSON persistence)

User data lives in `%APPDATA%/shantytown` (Windows) or `~/.config/shantytown`. All stores use **atomic temp-file swap + corrupt-file backup** and carry a `version` field for migrations.

- **profiles.py** — `ProfileStore` → `profiles.json`. Profile = UUID + name + email + DPAPI-encrypted token + timestamps. First profile auto-promoted to default; default reassigned if deleted.
- **games.py** — `GameStore` → `games.json`, keyed by product_id. `GameConfig` = exe_path (None ⇒ needs setup) + profile_id (None ⇒ use default) + favorite + last_played_at + display_name override.
- **settings.py** — `SettingsStore` → `settings.json`. Singleton: theme (system/light/dark) + tutorial_completed. get()/update() only.
- **paths.py** — path resolution; creates parent dirs. Also resolves bundled `known_games.json` in resources/.
- **known_games.py** — read-only loader of bundled static metadata (product_id → display name, exe-name candidates, tags, icon_url). Used to prettify UI and hint exe discovery. Not user-editable.

### gui/ (PyQt6)

`main_window.py` is the orchestrator: reads dmmgame.cnf → enriches with known_games + GameStore → renders a responsive card grid (1–6 columns on resize) → 2s poll timer tracks running subprocesses. Dialogs: login, profile, game_settings, progress, tutorial. Support widgets: toast, spinner, game_card. Theming in `theme.py` (Fusion + explicit QPalette for light/dark; Qt colorScheme for system) with design tokens in `fluent.py`; SVG icons recolored via `render_icon` in `icons.py`.

### Launch flow (the critical path)

A card click computes a `CardState` and steps through gates, each recursing after it resolves:

1. **NEEDS_SETUP** — auto-detect exe from known_games candidates, else `QFileDialog`; save `GameConfig`.
2. **NEEDS_LOGIN** — `LoginDialog` opens external browser + polls clipboard for the OAuth redirect (custom scheme like `dmmgameplayer5://` is caught by watching URL strings, not navigation). Issues token → stored encrypted in profile.
3. **READY** — `LaunchWorker` on a `QThread` (see workers.py) runs: `launch_game` API → fetch filelist → parallel MD5 verify (8) → parallel download (6) → `subprocess.Popen(..., DETACHED_PROCESS)`. Emits `progress(stage, current, total)` and `finished(success, message, popen)`; honors `isInterruptionRequested()` for the ProgressDialog Cancel button.
4. **RUNNING** — card disabled; poll timer flips it back when the PID exits.

**Silent launch** (`--launch=<id>`): main window stays hidden; only surfaces on missing config / expired token / error. On successful spawn the launcher quits, leaving the game running. Single-instance is enforced with a `QLocalServer` named pipe — a second instance forwards `raise` or `launch:<id>` over the pipe and exits.

All QThread workers follow: `moveToThread` → `thread.started→worker.run` → `worker.finished→thread.quit` → `thread.finished→worker.deleteLater`.

## Tests

pytest with **pytest-qt** (`qtbot`, `qtbot.waitUntil(...)`) and **pytest-httpx** (API mocking). `conftest.py` autouse-forces the KO locale so tests asserting Korean labels (e.g. `"설정 필요"`, `"실행"`) are stable; tests needing English call `init_translator("en")` themselves. GUI tests run headless via Qt's `-platform offscreen`. Key fixture: `tests/fixtures/dmmgame.cnf.sample` (5-game mock registry). ~165 tests across all core/store/gui modules.

## Gotchas

- `dmmgame.cnf` is read-only — never write to the official DMM registry.
- HWID dummies (hdd_serial/motherboard) and the `client-version: 5.4.8` header are the fragile spoofing surface; if DMM changes API version or starts validating hardware, these need updating.
- Games must already be installed by the official client, and a game must be launched once officially to be "linked" to the account (else `GameNotLinkedError`).
- No Co-Authored-By Claude trailer in commits (user preference).

## Reference

`docs/` contains the original PowerShell prototype notes and sprint plans. `reference-launch-tskx.ps1` (referenced there) is the verified PS1 implementation of the same auth/launch flow — the authoritative source for exact API headers, payload shapes, and MD5/download logic if the Python drifts.
