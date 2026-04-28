"""Single-file streaming downloader with progress callback.

Equivalent to ``Save-FileWithProgress`` in the reference PS1, minus the
retry wrapper — callers handle retries because they have better context
about whether a given failure is worth retrying.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

_DEFAULT_CHUNK = 81920


@dataclass(frozen=True)
class DownloadProgress:
    """One progress tick. ``total_bytes`` is ``None`` if not advertised."""

    bytes_received: int
    total_bytes: int | None
    file_name: str


def download_file(
    url: str,
    destination: Path,
    *,
    cookie: str | None = None,
    progress_cb: Callable[[DownloadProgress], None] | None = None,
    chunk_size: int = _DEFAULT_CHUNK,
    client: httpx.Client | None = None,
    timeout: float = 600.0,
) -> None:
    """Stream ``url`` to ``destination``.

    The parent directory is created if missing. If anything fails *after*
    the destination file has been opened for writing, the partial file
    is removed before the exception propagates. Files that already
    existed at ``destination`` before this call are *not* touched on
    failure.

    Args:
        url: Absolute URL to fetch.
        destination: Where to write the file.
        cookie: Optional ``Cookie`` header value (e.g. the CDN ``sign``).
        progress_cb: Called once per chunk with running totals.
        chunk_size: Bytes per read. Default matches the PS1.
        client: Optional pre-built ``httpx.Client``. If ``None``, a
            short-lived one is created and closed at the end.
        timeout: Request timeout in seconds when creating the default
            client. Ignored when ``client`` is provided.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers: dict[str, str] = {}
    if cookie:
        headers["Cookie"] = cookie

    owns_client = client is None
    cli = client if client is not None else httpx.Client(
        timeout=timeout, follow_redirects=True
    )
    file_name = destination.name
    file_opened = False
    try:
        with cli.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            total_raw = resp.headers.get("Content-Length")
            total: int | None = (
                int(total_raw) if total_raw and total_raw.isdigit() else None
            )
            received = 0
            with destination.open("wb") as fh:
                file_opened = True
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    received += len(chunk)
                    if progress_cb is not None:
                        progress_cb(DownloadProgress(received, total, file_name))
    except BaseException:
        if file_opened:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        if owns_client:
            cli.close()
