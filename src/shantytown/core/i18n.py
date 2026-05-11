"""Two-language UI strings — Korean (the original) and English fallback.

We only ship two locales, so a flat dict keyed by short identifiers is
enough; pulling in ``gettext`` or Qt Linguist would be overkill for the
scope. The active translator is set once at startup via
``init_translator`` (which the ``--locale`` CLI flag drives) and read
from any module via the ``t()`` shortcut.

Lookups fall through KO (or whichever locale is active) → EN → the
key itself, so missing translations degrade visibly rather than
silently rendering empty strings.
"""

from __future__ import annotations

import locale as _locale
from typing import Final

KO: Final[str] = "ko"
EN: Final[str] = "en"
SUPPORTED: Final[tuple[str, ...]] = (KO, EN)


_STRINGS_KO: Final[dict[str, str]] = {
    # --- app-level ---
    "app.name": "판자촌",
    # --- main window ---
    "main.profile_button": "프로필 관리",
    "main.refresh_button": "새로고침",
    "main.cnf_missing.title": "dmmgame.cnf 없음",
    "main.cnf_missing.body": (
        "DMM Game Player의 설치 정보 파일을 찾지 못했습니다:\n"
        "{path}\n\n"
        "공식 DMM Game Player를 설치한 뒤 다시 시도해주세요."
    ),
    "main.no_profile.title": "프로필 필요",
    "main.no_profile.body": "프로필이 없습니다. 프로필 관리에서 먼저 만들어주세요.",
    "main.cannot_launch.title": "실행 불가",
    "main.cannot_launch.body": "게임 설정이 완료되지 않았습니다.",
    "main.progress_dialog.title": "게임 실행",
    "main.exe_detected.title": "실행 파일 자동 감지",
    "main.exe_detected.body": "<b>{name}</b> 파일을 발견했습니다. 이 파일을 사용할까요?",
    "main.choose_exe.title": "실행 파일 선택",
    "main.exe_filter": "실행 파일 (*.exe);;모든 파일 (*)",
    "main.theme.tooltip.system": "테마: 시스템 (클릭하여 변경)",
    "main.theme.tooltip.light": "테마: 라이트 (클릭하여 변경)",
    "main.theme.tooltip.dark": "테마: 다크 (클릭하여 변경)",
    "main.help_button.tooltip": "도움말",
    "main.refresh_button.tooltip": "새로고침",
    # --- tutorial ---
    "tutorial.title": "판자촌 사용 안내",
    "tutorial.skip": "건너뛰기",
    "tutorial.back": "이전",
    "tutorial.next": "다음",
    "tutorial.finish": "시작하기",
    "tutorial.page1.title": "1. 게임 설치",
    "tutorial.page1.body": (
        "원하는 게임을 먼저 DMM Game Player(공식 런처)에서 설치하세요.\n"
        "다운로드 단계에서는 VPN이 필요할 수 있습니다."
    ),
    "tutorial.page2.title": "2. 프로필 만들기",
    "tutorial.page2.body": "사용할 DMM 계정별로 프로필을 만드세요.",
    "tutorial.page3.title": "3. 게임 목록",
    "tutorial.page3.body": "PC에 설치된 게임은 자동으로 메인 화면에 표시됩니다.",
    "tutorial.page4.title": "4. 실행",
    "tutorial.page4.body": (
        "게임 카드를 클릭하면 실행됩니다. 프로필을 바꿔서 같은 게임을 "
        "다른 DMM 계정으로 실행할 수 있어요.\n"
        "실행 단계에는 VPN이 필요 없습니다."
    ),
    "tutorial.page5.title": "5. DMM 로그인",
    "tutorial.page5.body": (
        "처음 프로필로 게임을 실행하거나 로그인 정보가 만료되면 "
        "브라우저를 통해 DMM 계정에 로그인해 주세요.\n"
        "로그인 과정에는 VPN이 필요할 수 있습니다."
    ),
    # --- card ---
    "card.state.needs_setup": "설정 필요",
    "card.state.needs_login": "로그인 필요",
    "card.state.running": "실행 중",
    "card.state.ready": "실행",
    "card.profile_label": "프로필:",
    "card.profile.default": "기본 프로필 — {name}",
    "card.profile.default_empty": "기본 프로필 — (없음)",
    "card.settings_tooltip": "게임 설정 (실행 경로 등)",
    # --- login dialog ---
    "login.title": "DMM 계정 설정",
    "login.heading": "DMM 계정 로그인",
    "login.step1": "아래 버튼을 눌러 브라우저에서 DMM 로그인 페이지를 여세요.",
    "login.open_button": "로그인 페이지 열기",
    "login.step2": (
        "DMM 계정 로그인을 마치면 주소창의 URL을 복사하세요. "
        "앱이 자동으로 인식합니다. (DMM Launcher가 함께 실행될 수 있어요.)"
    ),
    "login.preparing": "로그인 URL을 준비하고 있습니다…",
    "login.fallback_note": "※ URL 자동 인식이 안 될 때 아래에 직접 붙여넣어 주세요.",
    "login.paste_placeholder": "리디렉션된 URL 또는 code 값",
    "login.submit": "제출",
    "login.after_open": "브라우저에서 로그인을 마치면 자동으로 진행됩니다.",
    "login.no_code.title": "코드를 찾을 수 없음",
    "login.no_code.body": "붙여넣은 값에서 code 파라미터를 찾지 못했습니다.",
    "login.saving": "계정 정보를 저장하고 있습니다…",
    "login.timeout": (
        "5분 내에 로그인이 감지되지 않았습니다. "
        "다시 시도하거나 URL을 직접 붙여넣으세요."
    ),
    "login.url_failed": "로그인 URL을 가져오지 못했습니다: {error}",
    "login.failed": "계정 설정 실패: {error}",
    "login.completed.title": "계정 설정 완료",
    "login.completed.body": "'{name}' 프로필의 계정이 연결됐습니다.",
    # --- profile dialog ---
    "profile.title": "프로필 관리",
    "profile.heading": "DMM 계정 프로필",
    "profile.add_button": "+ 추가",
    "profile.delete_button": "삭제",
    "profile.rename_button": "이름 변경",
    "profile.default_button": "기본으로 설정",
    "profile.logout_button": "로그아웃",
    "profile.close_button": "닫기",
    "profile.relogin_badge": "[재로그인 필요]",
    "profile.last_used": "마지막 사용: {date}",
    "profile.never_used_dash": "—",
    "profile.default_marker": "(기본)",
    "profile.add.title": "새 프로필",
    "profile.add.prompt": "프로필 이름을 입력하세요:",
    "profile.rename.title": "이름 변경",
    "profile.rename.prompt": "새 이름:",
    "profile.delete.title": "프로필 삭제",
    "profile.delete.body": (
        "'{name}' 프로필을 삭제할까요? 저장된 계정 정보도 함께 사라집니다."
    ),
    "profile.logout.title": "로그아웃",
    "profile.logout.body": (
        "'{name}' 프로필에서 로그아웃할까요?\n"
        "계정 정보가 삭제되고 다시 로그인해야 게임을 실행할 수 있습니다."
    ),
    "profile.already_logout.title": "이미 로그아웃 상태",
    "profile.already_logout.body": "이 프로필에는 저장된 계정 정보가 없습니다.",
    # --- game settings dialog ---
    "game_settings.title": "{name} 설정",
    "game_settings.install_path": "설치 경로:",
    "game_settings.exe_label": "실행 파일 경로",
    "game_settings.browse": "찾아보기…",
    "game_settings.choose.title": "실행 파일 선택",
    "game_settings.empty.title": "경로 비어있음",
    "game_settings.empty.body": "실행 파일 경로를 입력하세요.",
    "game_settings.missing.title": "파일 없음",
    "game_settings.missing.body": (
        "'{path}' 파일이 존재하지 않습니다. 그래도 저장할까요?"
    ),
    "game_settings.display_name_label": "표시 이름",
    "game_settings.display_name_placeholder": "기본값 사용 ({default})",
    "game_settings.create_shortcut": "바탕화면에 바로가기 만들기",
    "game_settings.creating_shortcut": "생성중",
    "game_settings.shortcut.success.title": "바로가기 생성 완료",
    "game_settings.shortcut.success.body": (
        "바탕화면에 '{name}' 바로가기를 만들었습니다."
    ),
    "game_settings.shortcut.failed.title": "바로가기 생성 실패",
    "game_settings.shortcut.failed.body": "바로가기를 만들지 못했습니다: {error}",
    # --- silent launch (--launch=<id> from desktop shortcut) ---
    "silent_launch.not_installed.title": "게임이 설치되어 있지 않음",
    "silent_launch.not_installed.body": (
        "'{product_id}' 게임이 DMM Game Player에 설치되어 있지 않습니다.\n"
        "공식 런처에서 먼저 설치한 뒤 다시 시도해주세요."
    ),
    # --- progress dialog ---
    "progress.preparing": "준비 중…",
    "progress.failed": "실패: {message}",
    "progress.cancel_requested": "취소 요청됨…",
    # --- worker error / progress messages ---
    "worker.error.api": "DMM API 오류: {error}",
    "worker.error.not_linked": (
        "이 DMM 계정에 해당 게임이 연동되어 있지 않습니다.\n"
        "\n"
        "공식 DMM Game Player(DMM Launcher)를 실행하여 게임을 한 번 시작하면 "
        "계정에 연동됩니다. 이후 판자촌에서 다시 실행해 주세요."
    ),
    "worker.error.auth_invalid": (
        "DMM 인증 정보가 만료되었거나 유효하지 않습니다.\n"
        "\n"
        "프로필 관리에서 해당 프로필을 로그아웃한 뒤 다시 로그인해 주세요."
    ),
    "worker.error.file_not_found": "파일을 찾을 수 없습니다: {error}",
    "worker.error.unexpected": "예상치 못한 오류: {error}",
    "worker.cancelled": "취소됨",
    "worker.requesting_launch": "게임 실행 권한 요청 중…",
    "worker.fetching_filelist": "파일 목록 가져오는 중…",
    "worker.verifying": "파일 검증 중",
    "worker.downloading.path": "다운로드 ({path})",
    "worker.downloading.progress": "다운로드 ({idx}/{total}) {file_name}",
    "worker.downloading.aggregate": "다운로드 중 ({done} / {total})",
    "worker.launching": "게임 실행 중…",
    "worker.detail_separator": "--- 응답 본문 ---",
}


_STRINGS_EN: Final[dict[str, str]] = {
    "app.name": "Shantytown",
    "main.profile_button": "Profiles",
    "main.refresh_button": "Refresh",
    "main.cnf_missing.title": "dmmgame.cnf not found",
    "main.cnf_missing.body": (
        "Could not find the DMM Game Player installation index:\n"
        "{path}\n\n"
        "Install the official DMM Game Player and try again."
    ),
    "main.no_profile.title": "Profile required",
    "main.no_profile.body": (
        "No profiles yet. Create one from the profile manager first."
    ),
    "main.cannot_launch.title": "Cannot launch",
    "main.cannot_launch.body": "Game setup is incomplete.",
    "main.progress_dialog.title": "Launching",
    "main.exe_detected.title": "Auto-detected executable",
    "main.exe_detected.body": "Found <b>{name}</b>. Use this file?",
    "main.choose_exe.title": "Choose executable",
    "main.exe_filter": "Executables (*.exe);;All files (*)",
    "main.theme.tooltip.system": "Theme: System (click to change)",
    "main.theme.tooltip.light": "Theme: Light (click to change)",
    "main.theme.tooltip.dark": "Theme: Dark (click to change)",
    "main.help_button.tooltip": "Help",
    "main.refresh_button.tooltip": "Refresh",
    "tutorial.title": "Welcome to Shantytown",
    "tutorial.skip": "Skip",
    "tutorial.back": "Back",
    "tutorial.next": "Next",
    "tutorial.finish": "Get started",
    "tutorial.page1.title": "1. Install your games",
    "tutorial.page1.body": (
        "Install your games through DMM Game Player (the official client) first.\n"
        "A VPN may be needed during download."
    ),
    "tutorial.page2.title": "2. Create profiles",
    "tutorial.page2.body": "Create one profile per DMM account you'll use.",
    "tutorial.page3.title": "3. Your library",
    "tutorial.page3.body": (
        "Games installed on this PC appear on the main screen automatically."
    ),
    "tutorial.page4.title": "4. Play",
    "tutorial.page4.body": (
        "Click a game card to launch. Switching profiles lets you play "
        "the same game with a different DMM account.\n"
        "No VPN is needed to run games."
    ),
    "tutorial.page5.title": "5. Sign in to DMM",
    "tutorial.page5.body": (
        "The first time you launch a game with a profile (or after credentials "
        "expire), sign in to DMM in your browser.\n"
        "A VPN may be needed during sign-in."
    ),
    "card.state.needs_setup": "Setup needed",
    "card.state.needs_login": "Sign in required",
    "card.state.running": "Running",
    "card.state.ready": "Play",
    "card.profile_label": "Profile:",
    "card.profile.default": "Default — {name}",
    "card.profile.default_empty": "Default — (none)",
    "card.settings_tooltip": "Game settings (executable, etc.)",
    "login.title": "DMM sign-in",
    "login.heading": "Sign in to DMM",
    "login.step1": "Click the button to open the DMM sign-in page in your browser.",
    "login.open_button": "Open sign-in page",
    "login.step2": (
        "After signing in, copy the URL from your address bar. "
        "The app will pick it up automatically. "
        "(DMM Launcher may also open — that's fine.)"
    ),
    "login.preparing": "Preparing the sign-in URL…",
    "login.fallback_note": (
        "※ If auto-detect doesn't work, paste the URL below."
    ),
    "login.paste_placeholder": "Redirected URL or code value",
    "login.submit": "Submit",
    "login.after_open": (
        "Once you finish signing in, the app will continue automatically."
    ),
    "login.no_code.title": "Code not found",
    "login.no_code.body": "Couldn't find the code parameter in the value you pasted.",
    "login.saving": "Saving credentials…",
    "login.timeout": (
        "No sign-in detected within 5 minutes. "
        "Try again or paste the URL manually."
    ),
    "login.url_failed": "Couldn't fetch the sign-in URL: {error}",
    "login.failed": "Sign-in failed: {error}",
    "login.completed.title": "Sign-in complete",
    "login.completed.body": "Profile '{name}' is now linked to a DMM account.",
    "profile.title": "Profile manager",
    "profile.heading": "DMM account profiles",
    "profile.add_button": "+ Add",
    "profile.delete_button": "Delete",
    "profile.rename_button": "Rename",
    "profile.default_button": "Set as default",
    "profile.logout_button": "Sign out",
    "profile.close_button": "Close",
    "profile.relogin_badge": "[Sign-in required]",
    "profile.last_used": "Last used: {date}",
    "profile.never_used_dash": "—",
    "profile.default_marker": "(default)",
    "profile.add.title": "New profile",
    "profile.add.prompt": "Profile name:",
    "profile.rename.title": "Rename",
    "profile.rename.prompt": "New name:",
    "profile.delete.title": "Delete profile",
    "profile.delete.body": (
        "Delete profile '{name}'? Stored credentials will be removed too."
    ),
    "profile.logout.title": "Sign out",
    "profile.logout.body": (
        "Sign out of profile '{name}'?\n"
        "Credentials will be removed; you'll need to sign in again to play."
    ),
    "profile.already_logout.title": "Already signed out",
    "profile.already_logout.body": "This profile has no stored credentials.",
    "game_settings.title": "{name} settings",
    "game_settings.install_path": "Install path:",
    "game_settings.exe_label": "Executable path",
    "game_settings.browse": "Browse…",
    "game_settings.choose.title": "Choose executable",
    "game_settings.empty.title": "Empty path",
    "game_settings.empty.body": "Enter an executable path.",
    "game_settings.missing.title": "File missing",
    "game_settings.missing.body": (
        "'{path}' does not exist. Save anyway?"
    ),
    "game_settings.display_name_label": "Display name",
    "game_settings.display_name_placeholder": "Use default ({default})",
    "game_settings.create_shortcut": "Create desktop shortcut",
    "game_settings.creating_shortcut": "Creating",
    "game_settings.shortcut.success.title": "Shortcut created",
    "game_settings.shortcut.success.body": (
        "Created a desktop shortcut for '{name}'."
    ),
    "game_settings.shortcut.failed.title": "Shortcut creation failed",
    "game_settings.shortcut.failed.body": "Could not create the shortcut: {error}",
    "silent_launch.not_installed.title": "Game not installed",
    "silent_launch.not_installed.body": (
        "'{product_id}' isn't installed via DMM Game Player.\n"
        "Install it through the official client first, then try again."
    ),
    "progress.preparing": "Preparing…",
    "progress.failed": "Failed: {message}",
    "progress.cancel_requested": "Cancelling…",
    "worker.error.api": "DMM API error: {error}",
    "worker.error.not_linked": (
        "This DMM account hasn't been linked to that game yet.\n"
        "\n"
        "Open the official DMM Game Player (DMM Launcher) and start the game "
        "once to register the link, then try again from Shantytown."
    ),
    "worker.error.auth_invalid": (
        "Your DMM credentials are expired or invalid.\n"
        "\n"
        "Sign out of this profile from the profile manager and sign in again."
    ),
    "worker.error.file_not_found": "File not found: {error}",
    "worker.error.unexpected": "Unexpected error: {error}",
    "worker.cancelled": "Cancelled",
    "worker.requesting_launch": "Requesting launch authorization…",
    "worker.fetching_filelist": "Fetching file list…",
    "worker.verifying": "Verifying files",
    "worker.downloading.path": "Downloading ({path})",
    "worker.downloading.progress": "Downloading ({idx}/{total}) {file_name}",
    "worker.downloading.aggregate": "Downloading ({done} / {total})",
    "worker.launching": "Launching…",
    "worker.detail_separator": "--- Response body ---",
}


_BUNDLES: Final[dict[str, dict[str, str]]] = {
    KO: _STRINGS_KO,
    EN: _STRINGS_EN,
}


class Translator:
    """Resolves a key against the active locale, falling back to EN."""

    def __init__(self, lang: str) -> None:
        self._lang = lang if lang in _BUNDLES else EN
        self._bundle = _BUNDLES[self._lang]

    @property
    def lang(self) -> str:
        return self._lang

    def __call__(self, key: str, **kwargs: object) -> str:
        template = self._bundle.get(key)
        if template is None:
            template = _STRINGS_EN.get(key, key)
        if not kwargs:
            return template
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template


_active: Translator | None = None


def detect_system_lang() -> str:
    """Return ``"ko"`` if the OS locale starts with ``ko``, else ``"en"``."""
    raw = ""
    try:
        raw = _locale.getlocale()[0] or ""
    except (TypeError, ValueError):
        raw = ""
    if not raw:
        try:
            # Deprecated in 3.11+ but useful as a last resort on systems
            # where ``getlocale`` returns None before ``setlocale``.
            raw = _locale.getdefaultlocale()[0] or ""
        except (TypeError, ValueError, AttributeError):
            raw = ""
    return KO if raw.lower().startswith("ko") else EN


def normalize_lang(value: str) -> str:
    """Normalize a user-supplied locale string to a supported key.

    Accepts ``ko``, ``en``, ``ko_KR``, ``en-US``, ``ko_KR.UTF-8``, …
    Anything unrecognised falls back to English.
    """
    head = value.lower().replace("-", "_").split("_", 1)[0].split(".", 1)[0]
    return head if head in _BUNDLES else EN


def init_translator(override: str | None = None) -> Translator:
    """Set the global translator and return it.

    Args:
        override: Locale string from ``--locale=``. ``None`` falls back
            to OS-detected locale.
    """
    global _active
    lang = normalize_lang(override) if override else detect_system_lang()
    _active = Translator(lang)
    return _active


def get_active() -> Translator:
    global _active
    if _active is None:
        _active = Translator(detect_system_lang())
    return _active


def t(key: str, **kwargs: object) -> str:
    """Translate ``key`` using the active translator (lazy-init to system)."""
    return get_active()(key, **kwargs)
