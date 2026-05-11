"""Windows desktop shortcut (``.lnk``) creation.

Built on PowerShell's ``WScript.Shell`` COM helper — same primitive
the Windows installer toolchain uses. We invoke ``powershell.exe`` as
a subprocess and pipe a short script in, which keeps us free of any
Python COM dependency (``pywin32``) and works out-of-the-box on any
Windows install.

The shortcut targets the *Shantytown* exe with a ``--launch=<id>``
argument, not the game's own exe. That way every launch goes through
our auth / verify / update flow even when started from the desktop —
no chance of the user double-clicking a shortcut that bypasses our
launcher and then wonders why the game errors out on a stale token.

The *icon* is pulled from the game's own exe so the desktop entry
looks like the game, not like a launcher with a generic logo. When
no game exe is available (game still in setup-needed state), we fall
back to Shantytown's own icon — the shortcut still works, it just
shows our logo until the user configures the exe and recreates it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class ShortcutError(RuntimeError):
    """Raised when shortcut creation fails for any reason — bad path,
    AV intervention, PowerShell missing, etc."""


def _desktop_dir() -> Path:
    """Best-effort resolution of the user's Desktop directory.

    ``USERPROFILE\\Desktop`` is right ~99% of the time. Localised
    Windows or OneDrive-redirected Desktop is the edge case; for those
    we'd want ``SHGetKnownFolderPath(FOLDERID_Desktop)``, but that
    would pull in ``pywin32``. Skip for now and fall back gracefully.
    """
    candidates: list[Path] = []
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidates.append(Path(profile) / "Desktop")
        candidates.append(Path(profile) / "OneDrive" / "Desktop")
    home_desktop = Path.home() / "Desktop"
    candidates.append(home_desktop)
    for c in candidates:
        if c.is_dir():
            return c
    raise ShortcutError("Desktop folder not found")


def _shantytown_exe() -> Path:
    """Path to launch when the shortcut is double-clicked.

    Frozen build: ``sys.executable`` is the exe itself.
    Dev / source run: there's no exe to point at, so we point at
    ``python.exe`` and pass ``-m shantytown`` — the shortcut still
    works for testing, just shows ``python.exe`` as the icon.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.executable)


def _shantytown_args(product_id: str) -> str:
    """Argument string for ``WScript.Shell``'s ``.Arguments`` slot."""
    base = f"--launch={product_id}"
    if getattr(sys, "frozen", False):
        return base
    # Source-run shortcut needs the module spec too.
    return f"-m shantytown {base}"


def _sanitise_filename(name: str) -> str:
    """Strip characters Windows forbids in filenames."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in bad else ch for ch in name).strip(" .")
    return cleaned or "Shantytown"


def create_desktop_shortcut(
    name: str,
    product_id: str,
    icon_path: Path | None = None,
) -> Path:
    """Create a desktop ``.lnk`` that launches Shantytown for one game.

    Args:
        name: Display name shown on the desktop. Forbidden filename
            characters get replaced with ``_``.
        product_id: DMM product id to pass via ``--launch=<id>``.
        icon_path: Game executable to read the icon from. When ``None``
            (or the path doesn't resolve to a real file) we fall back
            to Shantytown's own exe icon. The user's expectation is
            "looks like the game on my desktop" — passing the game's
            real exe gets the icon Windows extracts from the binary's
            embedded resource table.

    Returns:
        The full path to the created ``.lnk`` file.

    Raises:
        ShortcutError: If the platform isn't Windows, the desktop dir
            can't be located, PowerShell is missing, or the COM call
            returns non-zero.
    """
    if sys.platform != "win32":
        raise ShortcutError("Desktop shortcuts are only supported on Windows.")

    desktop = _desktop_dir()
    lnk_path = desktop / f"{_sanitise_filename(name)}.lnk"
    target = _shantytown_exe()
    arguments = _shantytown_args(product_id)
    work_dir = target.parent

    icon_source: Path = (
        icon_path if icon_path is not None and icon_path.is_file() else target
    )

    # Single-quoted PowerShell strings — we double up internal single
    # quotes per PowerShell's escape rules.
    def _q(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    script = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$lnk = $ws.CreateShortcut({_q(str(lnk_path))});"
        f"$lnk.TargetPath = {_q(str(target))};"
        f"$lnk.Arguments = {_q(arguments)};"
        f"$lnk.WorkingDirectory = {_q(str(work_dir))};"
        f"$lnk.IconLocation = {_q(str(icon_source) + ',0')};"
        "$lnk.Save();"
    )

    # ``CREATE_NO_WINDOW`` (Windows-only, 0x08000000) suppresses the
    # console window the child process would otherwise open. Without
    # it, frozen PyInstaller builds (``--windowed``, no parent console)
    # flash a powershell console for the 1-3 s the COM call takes —
    # very visible and reads as a glitch. ``getattr`` is defensive
    # against partial type-stub coverage even though we're guarded
    # on ``sys.platform == "win32"`` at the function entry.
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=no_window,
        )
    except (FileNotFoundError, OSError) as e:
        raise ShortcutError(f"PowerShell unavailable: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise ShortcutError("Shortcut creation timed out.") from e

    if result.returncode != 0 or not lnk_path.exists():
        msg = (result.stderr or result.stdout or "unknown error").strip()
        raise ShortcutError(msg or "shortcut not written")

    return lnk_path
