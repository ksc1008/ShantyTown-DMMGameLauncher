"""Pure data structures shared by the rest of ``core``.

These are intentionally trivial — no methods beyond what ``@dataclass``
gives us — so they can serve as a stable contract between the API layer,
the verifier, the downloader, and the GUI/store layers above.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileEntry:
    """One row in the CDN ``data.file_list`` response.

    ``hash`` is the lowercase hex MD5 of the expected file contents.
    ``remote_path`` is appended to the CDN domain to form the download URL.
    """

    local_path: str
    remote_path: str
    hash: str
    size: int


@dataclass(frozen=True)
class LaunchResponse:
    """Decoded response from ``POST /v5/r2/launch/cl``.

    The CDN domain is *not* part of the launch response in practice — it
    arrives with the file-list response, so it lives on
    ``DmmApiClient.get_filelist`` instead. (The doc spec listed
    ``cdn_domain`` here, but the reference PS1 — the source of truth for
    response shapes — only has ``data.domain`` on the file-list call.)
    """

    cdn_sign: str
    file_list_url: str
    execute_args: str


@dataclass(frozen=True)
class InstalledGame:
    """One installed entry from ``%APPDATA%/dmmgameplayer5/dmmgame.cnf``."""

    product_id: str
    game_type: str
    install_path: Path
    version: str


@dataclass(frozen=True)
class HardwareIds:
    """Identifiers sent to ``/launch/cl``.

    ``mac_address`` is lowercase, colon-separated (``aa:bb:cc:dd:ee:ff``).
    ``hdd_serial`` and ``motherboard`` are SHA256 hex strings — for now we
    submit fixed dummy values that match the reference PS1.
    """

    mac_address: str
    hdd_serial: str
    motherboard: str
