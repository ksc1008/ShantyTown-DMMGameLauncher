"""Background workers for slow / blocking tasks.

Anything that talks to the network (token check, launch authorization,
file list fetch) or the disk (MD5 verify, downloads) lives here. The UI
thread only handles signals.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from shantytown.core.api import (
    AuthInvalidError,
    DmmApiClient,
    DmmApiError,
    GameNotLinkedError,
)
from shantytown.core.debug import is_debug
from shantytown.core.download import download_file
from shantytown.core.hwid import get_default_hardware_ids
from shantytown.core.i18n import t
from shantytown.core.models import HardwareIds
from shantytown.core.verify import VerificationResult, verify_files

# Sweet spot for CDN-backed downloads: enough parallelism to keep TCP
# slow-start from dominating per-file time, low enough that CloudFront-
# style providers don't rate-limit a single source IP. The official
# clients (Steam / DMM Game Player / EGS) sit in the same band.
DOWNLOAD_CONCURRENCY = 6


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
            self._parallel_download(needs, cdn_domain, launch.cdn_sign)
            if self._interrupted():
                self.finished.emit(False, cancelled, None)
                return

        if self._interrupted():
            self.finished.emit(False, cancelled, None)
            return

        # Hand off to the OS — game runs in its own process.
        self.progress.emit(t("worker.launching"), 0, 0)
        popen = self._spawn_game(launch.execute_args)
        self.finished.emit(True, t("worker.launching"), popen)

    def _parallel_download(
        self,
        needs: list[VerificationResult],
        cdn_domain: str,
        cdn_sign: str,
    ) -> None:
        """Download all entries in parallel, respecting cancellation.

        Uses ``ThreadPoolExecutor`` with ``DOWNLOAD_CONCURRENCY`` workers
        because:

        - Each download is independent — different ``dest`` path, no
          shared mutable state. ``httpx.Client`` is thread-safe by spec.
        - TCP slow-start dominates per-file time on small assets;
          parallel streams amortise the ramp-up.
        - CloudFront-style CDNs cap per-connection bandwidth; multiple
          connections add up.

        Progress is reported as ``(done / total)`` rather than per-file
        chunk percentages — too many in-flight streams to show
        individual progress sensibly. A failure on any single file
        cancels still-pending futures and propagates; in-flight
        downloads finish naturally (``Future.cancel`` doesn't interrupt
        running work, but they're chunked-streamed so each completes
        within seconds).

        MD5 verification is the safety net — if a parallel write
        somehow corrupts a file, the next launch's verify pass catches
        it and re-downloads. No data-corruption risk in practice.
        """
        total = len(needs)

        def _agg_label(done: int) -> str:
            return t("worker.downloading.aggregate", done=done, total=total)

        self.progress.emit(_agg_label(0), 0, total)

        def _worker(entry: VerificationResult) -> None:
            if self._interrupted():
                return
            url = urljoin(cdn_domain, entry.file.remote_path)
            dest = self._install_dir / entry.file.local_path
            try:
                download_file(url, dest, cookie=cdn_sign)
            except httpx.HTTPError as e:
                raise RuntimeError(
                    f"download failed for {url}\n{type(e).__name__}: {e}"
                ) from e

        completed = 0
        with ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY) as pool:
            futures = [pool.submit(_worker, n) for n in needs]
            try:
                for fut in as_completed(futures):
                    if self._interrupted():
                        for f in futures:
                            if not f.done():
                                f.cancel()
                        return
                    fut.result()  # surfaces any worker exception
                    completed += 1
                    self.progress.emit(
                        _agg_label(completed), completed, total
                    )
            except Exception:
                for f in futures:
                    if not f.done():
                        f.cancel()
                raise

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
