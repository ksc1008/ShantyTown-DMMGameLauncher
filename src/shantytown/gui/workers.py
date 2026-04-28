"""Background workers for slow / blocking tasks.

Anything that talks to the network (token check, launch authorization,
file list fetch) or the disk (MD5 verify, downloads) lives here. The UI
thread only handles signals.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from shantytown.core.api import (
    AuthInvalidError,
    DmmApiClient,
    DmmApiError,
    GameNotLinkedError,
)
from shantytown.core.debug import is_debug
from shantytown.core.download import DownloadProgress, download_file
from shantytown.core.hwid import get_default_hardware_ids
from shantytown.core.i18n import t
from shantytown.core.models import HardwareIds
from shantytown.core.verify import verify_files


class TokenCheckWorker(QObject):
    """Checks a stored token's validity without blocking the UI."""

    finished = pyqtSignal(bool, str)  # (is_valid, error_msg_if_any)

    def __init__(self, api: DmmApiClient, token: str) -> None:
        super().__init__()
        self._api = api
        self._token = token

    def run(self) -> None:
        try:
            valid = self._api.check_token(self._token)
        except DmmApiError as e:
            self.finished.emit(False, str(e))
            return
        self.finished.emit(valid, "")


class LaunchWorker(QObject):
    """Full launch flow: launch_game → filelist → verify → download → exec.

    Emits ``progress(stage, current, total)`` updates and a final
    ``finished(success, message, popen)`` signal. ``popen`` is the
    ``subprocess.Popen`` for the running game (or ``None`` on failure)
    so the main window can poll its lifetime and show a "실행 중" badge.
    The Qt thread that owns this worker drives the loop; we honor
    ``QThread.currentThread().isInterruptionRequested()`` so the cancel
    button in the progress dialog can short-circuit.
    """

    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str, object)

    def __init__(
        self,
        api: DmmApiClient,
        token: str,
        product_id: str,
        game_type: str,
        install_dir: Path,
        exe_path: Path,
        hwid: HardwareIds | None = None,
    ) -> None:
        super().__init__()
        self._api = api
        self._token = token
        self._product_id = product_id
        self._game_type = game_type
        self._install_dir = install_dir
        self._exe_path = exe_path
        self._hwid = hwid

    def _interrupted(self) -> bool:
        thread = QThread.currentThread()
        return thread is not None and thread.isInterruptionRequested()

    def run(self) -> None:
        try:
            self._run_inner()
        except GameNotLinkedError as e:
            msg = t("worker.error.not_linked")
            if is_debug() and e.detail:
                msg += f"\n\n{t('worker.detail_separator')}\n{e.detail}"
            self.finished.emit(False, msg, None)
        except AuthInvalidError as e:
            msg = t("worker.error.auth_invalid")
            if is_debug() and e.detail:
                msg += f"\n\n{t('worker.detail_separator')}\n{e.detail}"
            self.finished.emit(False, msg, None)
        except DmmApiError as e:
            msg = t("worker.error.api", error=str(e))
            if is_debug() and e.detail:
                msg += f"\n\n{t('worker.detail_separator')}\n{e.detail}"
            self.finished.emit(False, msg, None)
        except FileNotFoundError as e:
            msg = t("worker.error.file_not_found", error=str(e))
            if is_debug():
                import traceback

                msg += f"\n\n{traceback.format_exc()}"
            self.finished.emit(False, msg, None)
        except Exception as e:
            msg = t("worker.error.unexpected", error=str(e))
            if is_debug():
                import traceback

                msg += f"\n\n{traceback.format_exc()}"
            self.finished.emit(False, msg, None)

    def _run_inner(self) -> None:
        cancelled = t("worker.cancelled")
        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        hwid = self._hwid or get_default_hardware_ids()

        self.progress.emit(t("worker.requesting_launch"), 0, 0)
        launch = self._api.launch_game(
            self._token, self._product_id, self._game_type, hwid
        )
        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        self.progress.emit(t("worker.fetching_filelist"), 0, 0)
        entries, cdn_domain = self._api.get_filelist(
            self._token, launch.file_list_url
        )
        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        # Verify (parallel MD5)
        total = len(entries)
        verify_label = t("worker.verifying")
        self.progress.emit(verify_label, 0, total)

        def verify_cb(done: int, n: int) -> None:
            self.progress.emit(verify_label, done, n)

        results = verify_files(
            entries, self._install_dir, max_workers=8, progress_cb=verify_cb
        )
        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        needs = [r for r in results if r.needs_download]
        if needs:
            total_dl = len(needs)
            for idx, r in enumerate(needs, start=1):
                if self._interrupted():
                    self.finished.emit(False, cancelled, None)
                    return
                self.progress.emit(
                    t("worker.downloading.path", path=r.file.local_path),
                    idx - 1,
                    total_dl,
                )
                url = f"{cdn_domain.rstrip('/')}{r.file.remote_path}"
                dest = self._install_dir / r.file.local_path

                def dl_cb(
                    p: DownloadProgress,
                    _idx: int = idx,
                    _total: int = total_dl,
                ) -> None:
                    pct = (
                        int((p.bytes_received / p.total_bytes) * 100)
                        if p.total_bytes
                        else 0
                    )
                    self.progress.emit(
                        t(
                            "worker.downloading.progress",
                            idx=_idx,
                            total=_total,
                            file_name=p.file_name,
                        ),
                        pct,
                        100,
                    )

                download_file(
                    url,
                    dest,
                    cookie=launch.cdn_sign,
                    progress_cb=dl_cb,
                )

        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        # Hand off to the OS — game runs in its own process.
        self.progress.emit(t("worker.launching"), 0, 0)
        popen = self._spawn_game(launch.execute_args)
        self.finished.emit(True, t("worker.launching"), popen)

    def _spawn_game(self, execute_args: str) -> subprocess.Popen[bytes]:
        """Start the game executable, detached from this process.

        Returns the ``Popen`` so the main window can poll for the game's
        exit and flip the card status back from "실행 중" to "실행".
        """
        import shlex

        # ``execute_args`` looks like ``/viewer_id=... /onetime_token=... /access_token=...``
        # — POSIX-style splitting handles this fine on Windows too.
        argv = [str(self._exe_path), *shlex.split(execute_args, posix=False)]
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
        return subprocess.Popen(
            argv,
            cwd=str(self._exe_path.parent),
            creationflags=creationflags,
            close_fds=True,
        )


def utc_now() -> datetime:
    """Convenience for stamping ``last_used_at`` / ``last_played_at``."""
    return datetime.now(UTC)
