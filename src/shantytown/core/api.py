"""HTTP client for the DMM gameplay API.

Header values, payload shapes, and the cookie hack are all transcribed
verbatim from ``docs/reference-launch-tskx.ps1``. If something feels
arbitrary, that script is the source of truth — change here only after
the script changes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, ClassVar
from urllib.parse import urljoin

import httpx

from .models import FileEntry, HardwareIds, LaunchResponse


class DmmApiError(RuntimeError):
    """Raised on any non-success outcome from the DMM gameplay API.

    ``detail`` carries the verbatim response body or raw decoded payload
    so debug-mode UI can show the full server response on failure. The
    user-facing summary in ``str(e)`` stays short either way.
    """

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class GameNotLinkedError(DmmApiError):
    """Raised when DMM rejects a launch with a 3xx server code.

    The product is installed and the token is valid, but the DMM
    account behind the token has never opened this game from the
    official DMM Game Player — the server hasn't recorded the link
    between account and product, so it refuses to mint launch
    credentials. DMM emits different 3xx codes depending on which
    pre-flight check failed (314, 31x variants, etc.); the remediation
    is the same in every case, so we collapse the whole range under
    this exception.
    """


class AuthInvalidError(DmmApiError):
    """Raised when DMM rejects a request with code 203.

    The token we sent is no longer accepted — usually because it
    expired or was invalidated server-side. The remediation is on the
    user side: log out of the profile and log in again to mint a fresh
    token.
    """


# Cookie pinned on every request to the DMM gameplay API. Two pieces:
#
# - ``age_check_done=1``: skips the adult-content age gate the API would
#   otherwise return for unauthenticated browsing.
# - ``ckcy_remedied_check=ec_mrnhbtk``: a magic value the DMM gateway
#   accepts as proof that a region-lock remediation has been granted.
#   Without it, the gateway rejects requests from non-Japan IPs as
#   "service unavailable in your region" — even on the *auth*
#   endpoints, before any token check happens. This is the same trick
#   the public uBlock Origin / AdGuard ``trusted-set-cookie``
#   scriptlets use for browser-side bypasses; we send it on every API
#   call so the user doesn't need a VPN.
#
# We keep this in the client's default headers (rather than per-call
# overrides like the reference PS1 did) so the auth endpoints get it
# too. The PS1 was developed in JP where the bypass wasn't needed.
_BASE_COOKIE = "age_check_done=1; ckcy_remedied_check=ec_mrnhbtk"

# DMM returns different ``3xx`` codes at different stages of the
# account-link flow (314 when the game has never been launched, 31x for
# variants on missing entitlements, etc.). The remediation is the same
# regardless: open the official DMM Game Player and start the game once.
# We treat the entire 300-399 range as "game not linked".
_GAME_NOT_LINKED_RANGE = range(300, 400)
# Token-rejection code: the gateway accepted the request shape but the
# bearer token is no longer valid. User has to re-authenticate.
_AUTH_INVALID_CODE = 203


def _classify_error(raw: dict[str, Any], detail: str) -> DmmApiError | None:
    """Map a DMM response code to a typed exception, or return ``None``.

    Centralised so ``launch_game`` and ``get_filelist`` can share the
    same dispatch table — both endpoints can produce either failure.
    """
    code = _extract_error_code(raw)
    if code is None:
        return None
    if code in _GAME_NOT_LINKED_RANGE:
        return GameNotLinkedError(
            f"이 계정에 해당 게임이 연동되어 있지 않습니다 (server code {code}).",
            detail=detail,
        )
    if code == _AUTH_INVALID_CODE:
        return AuthInvalidError(
            f"인증 정보가 만료되었거나 유효하지 않습니다 (server code {code}).",
            detail=detail,
        )
    return None


def _extract_error_code(raw: dict[str, Any]) -> int | None:
    """Pull a numeric error code out of an error response.

    DMM's gameplay API doesn't expose a fully documented schema, so we
    probe the common locations: a top-level ``result_code`` /
    ``code`` / ``error_code``, or a nested ``error.code``. The first
    integer wins.
    """
    for key in ("result_code", "code", "error_code"):
        v = raw.get(key)
        if isinstance(v, int):
            return v
    nested = raw.get("error")
    if isinstance(nested, dict):
        v = nested.get("code")
        if isinstance(v, int):
            return v
    return None


class DmmApiClient:
    """Synchronous client for the DMM gameplay API.

    All public methods retry up to ``MAX_ATTEMPTS`` times on network
    errors and 5xx responses with exponential backoff. 4xx responses do
    not retry — they're wrapped in ``DmmApiError`` and raised immediately.
    """

    BASE: ClassVar[str] = "https://apidgp-gameplayer.games.dmm.com"
    HEADERS: ClassVar[dict[str, str]] = {
        "Content-Type": "application/json",
        "client-app": "DMMGamePlayer5",
        "client-version": "5.4.8",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-dest": "empty",
        "accept-encoding": "gzip, deflate, br, zstd",
        "user-agent": "DMMGamePlayer5-Win/5.4.8 Electron/34.3.0",
        # Region-lock + adult-gate bypass — see ``_BASE_COOKIE`` comment.
        "cookie": _BASE_COOKIE,
    }
    MAX_ATTEMPTS: ClassVar[int] = 3
    BASE_DELAY: ClassVar[float] = 1.0

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = client if client is not None else httpx.Client(
            headers=self.HEADERS, timeout=timeout
        )
        self._owns_client = client is None
        self._sleep: Callable[[float], None] = sleep if sleep is not None else time.sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DmmApiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- public API ---

    def get_login_url(self) -> str:
        """Return the OAuth-style login URL the user opens in a browser."""
        data = self._request(
            "POST",
            f"{self.BASE}/v5/auth/login/url",
            json_body={"prompt": "choose"},
        )
        url = self._extract(data, "data", "url")
        if not isinstance(url, str) or not url:
            raise DmmApiError("Login URL response did not contain data.url")
        return url

    def issue_token(self, code: str) -> str:
        """Exchange a one-shot ``code`` for an access token."""
        data = self._request(
            "POST",
            f"{self.BASE}/v5/auth/accesstoken/issue",
            json_body={"code": code},
        )
        token = self._extract(data, "data", "access_token")
        if not isinstance(token, str) or not token:
            raise DmmApiError("Token issue response did not contain data.access_token")
        return token

    def check_token(self, token: str, *, expires_in_seconds: int = 1209600) -> bool:
        """Return ``True`` if the token is still valid, ``False`` otherwise.

        A failed network/5xx call still raises ``DmmApiError``; only
        ``data.result == False`` returns ``False``.
        """
        data = self._request(
            "POST",
            f"{self.BASE}/v5/auth/accesstoken/check",
            json_body={"access_token": token, "expires_in_seconds": expires_in_seconds},
        )
        return bool(self._extract(data, "data", "result"))

    def launch_game(
        self,
        token: str,
        product_id: str,
        game_type: str,
        hwid: HardwareIds,
    ) -> LaunchResponse:
        """Request launch authorization. Returns the CDN sign + execute args."""
        body: dict[str, Any] = {
            "product_id": product_id,
            "game_type": game_type,
            "game_os": "win",
            "launch_type": "SCHEME",
            "mac_address": hwid.mac_address,
            "hdd_serial": hwid.hdd_serial,
            "motherboard": hwid.motherboard,
            "user_os": "win",
        }
        # Cookie is already on every request via the client's default
        # headers — only ``actauth`` needs to be added per-call.
        extra = {"actauth": token}
        raw = self._request(
            "POST",
            f"{self.BASE}/v5/r2/launch/cl",
            json_body=body,
            extra_headers=extra,
        )
        # Specific failures we have dedicated handling for (game not
        # linked, expired token, ...). Catch these BEFORE the generic
        # "missing data" branch so callers can surface tailored guidance.
        typed_err = _classify_error(raw, _pretty_json(raw))
        if typed_err is not None:
            raise typed_err

        d = raw.get("data") if isinstance(raw.get("data"), dict) else None
        if d is None:
            raise DmmApiError(
                "launch response missing 'data' object",
                detail=_pretty_json(raw),
            )
        try:
            return LaunchResponse(
                cdn_sign=str(d["sign"]),
                file_list_url=str(d["file_list_url"]),
                execute_args=str(d["execute_args"]),
            )
        except KeyError as e:
            raise DmmApiError(
                f"launch response missing field: {e}",
                detail=_pretty_json(raw),
            ) from e

    def get_filelist(
        self, token: str, file_list_url: str
    ) -> tuple[list[FileEntry], str]:
        """Fetch the CDN file list. Returns ``(entries, cdn_domain)``."""
        # ``urljoin`` handles all the edge cases: absolute URL passes
        # through unchanged, leading-slash relative replaces the path,
        # missing-slash relative is treated as relative to the root.
        url = urljoin(self.BASE, file_list_url)
        extra = {"actauth": token}
        raw = self._request("GET", url, extra_headers=extra)

        # Same typed-error dispatch as launch_game — the user's token
        # could expire between the launch call and this one.
        typed_err = _classify_error(raw, _pretty_json(raw))
        if typed_err is not None:
            raise typed_err

        d = raw.get("data") if isinstance(raw.get("data"), dict) else None
        if d is None:
            raise DmmApiError(
                "filelist response missing 'data' object",
                detail=_pretty_json(raw),
            )
        try:
            file_list_raw = d["file_list"]
            if not isinstance(file_list_raw, list):
                raise DmmApiError(
                    "filelist response 'file_list' is not a list",
                    detail=_pretty_json(raw),
                )
            entries = [
                FileEntry(
                    # API returns paths like "/GameAssembly.dll" — strip the
                    # leading separator so ``install_dir / local_path`` joins
                    # correctly on Windows (a leading "/" otherwise resets
                    # pathlib back to the drive root).
                    local_path=str(item["local_path"]).lstrip("/\\"),
                    remote_path=str(item["path"]),
                    hash=str(item["hash"]).lower(),
                    size=int(item["size"]),
                )
                for item in file_list_raw
            ]
            cdn_domain = str(d["domain"])
        except (KeyError, TypeError, ValueError) as e:
            raise DmmApiError(
                f"filelist response missing/invalid field: {e}",
                detail=_pretty_json(raw),
            ) from e
        return entries, cdn_domain

    # --- internals ---

    @staticmethod
    def _extract(data: dict[str, Any], *keys: str) -> Any:  # noqa: ANN401
        cur: Any = data
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    def _delay_for(self, attempt: int) -> float:
        # attempt is 1-indexed → 1s, 2s, 4s, ...
        return float(self.BASE_DELAY * (2 ** (attempt - 1)))

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        last_error: str | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                resp = self._client.request(
                    method, url, json=json_body, headers=extra_headers
                )
            except httpx.RequestError as e:
                last_error = f"network error: {e}"
                if attempt >= self.MAX_ATTEMPTS:
                    raise DmmApiError(
                        f"{last_error} (after {attempt} attempts)",
                        detail=repr(e),
                    ) from e
                self._sleep(self._delay_for(attempt))
                continue

            if 500 <= resp.status_code < 600:
                last_error = f"server error {resp.status_code}"
                if attempt >= self.MAX_ATTEMPTS:
                    raise DmmApiError(
                        f"{last_error} (after {attempt} attempts)",
                        detail=resp.text,
                    )
                self._sleep(self._delay_for(attempt))
                continue

            if resp.status_code >= 400:
                raise DmmApiError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                    detail=resp.text,
                )

            try:
                payload = resp.json()
            except ValueError as e:
                raise DmmApiError(
                    f"Invalid JSON response: {e}",
                    detail=resp.text,
                ) from e
            if not isinstance(payload, dict):
                raise DmmApiError(
                    f"Expected JSON object, got {type(payload).__name__}",
                    detail=resp.text,
                )
            return payload

        raise DmmApiError(f"retry loop exited unexpectedly: {last_error}")


def _pretty_json(value: object) -> str:
    """Best-effort JSON pretty-print for the ``detail`` field."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)
