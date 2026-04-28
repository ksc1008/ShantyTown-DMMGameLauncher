# DMM Launcher: Core 레이어 구현

## 사전 조건
프롬프트 0이 완료된 상태. 프로젝트 구조와 의존성이 준비됨.

## 참조 구현

이 작업과 함께 **`reference-launch-tskx.ps1`** 파일을 첨부받았을 것이다.
이 PowerShell 스크립트는 동일한 흐름의 검증된 프로토타입이다.
**API 헤더, 페이로드, 응답 구조는 이 스크립트를 절대적인 진실의 출처(source of truth)로 사용하라.**

### PS1에서 가져올 것
| PS1 함수 | Python 대응 |
|---|---|
| `Get-AccessToken` | `DmmApiClient.get_login_url()` + `issue_token()` |
| `Get-ValidAccessToken` | `check_token()` (파일 I/O는 store/ 레이어로 분리) |
| `Main` 함수 안의 `/launch/cl` POST | `launch_game()` |
| `Main` 함수 안의 filelist GET | `get_filelist()` |
| `Test-GameFiles` | `verify.py::verify_files` |
| `Save-FileWithProgress` | `download.py::download_file` |
| `$script:CommonHeaders` | `DmmApiClient.HEADERS` 클래스 변수 |

### PS1에서 무시할 것 (GUI 앱과 무관)
- `Test-Pwsh7`, `Get-PwshExecutable`, `Switch-ToConsoleMode` — PowerShell 환경 부트스트랩 로직
- `param([switch] $Hidden)` 및 관련 분기 — CLI 숨김 모드용
- 최상위 `try/catch`의 `Read-Host` 분기 — CLI 에러 처리용
- `dmmgame.cnf` 파싱 — Core가 아니라 별도 모듈 (`dmmcfg.py`)에서 처리

### 핵심 디테일 (PS1에서 발견되는 것들)
- `cookie` 헤더에 `age_check_done=1; ckcy_remedied_check=ec_mrnhbtk` 포함 (성인 인증)
- `client-app: DMMGamePlayer5`, `client-version: 5.4.8`, `user-agent: DMMGamePlayer5-Win/5.4.8 Electron/34.3.0`
- `/launch/cl` 페이로드의 `hdd_serial`, `motherboard`는 빈 문자열의 SHA256 해시 (모든 사용자 동일)
- `cdn_sign`은 다운로드 시 `Cookie` 헤더로 전달
- 파일 해시는 소문자 16진수 MD5

## 이 단계의 산출물

`src/dmm_launcher/core/` 아래 구현:

### models.py
타입 안전한 데이터 클래스 (`@dataclass(frozen=True)`):
- `FileEntry`: local_path, remote_path, hash, size
- `LaunchResponse`: cdn_sign, file_list_url, execute_args, cdn_domain
- `InstalledGame`: product_id, game_type, install_path, version (dmmgame.cnf 파싱 결과)
- `HardwareIds`: mac_address, hdd_serial, motherboard

### dmmcfg.py
```python
def parse_dmmgame_cnf(path: Path) -> list[InstalledGame]: ...
def get_default_cnf_path() -> Path:  # %APPDATA%\dmmgameplayer5\dmmgame.cnf
    ...
```
- `installed: false`인 항목은 제외
- 파일 없으면 `FileNotFoundError`

### hwid.py
```python
def get_mac_address() -> str: ...  # 'aa:bb:cc:dd:ee:ff' 형태
def get_default_hardware_ids() -> HardwareIds: ...
```
- 기존 PowerShell처럼 hdd_serial/motherboard는 고정 SHA256 더미값 사용
  (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`,
   `487578a3684a308fca6319f990c3f18db162efcfe97ba8e441864f01deb68d42`)
- MAC은 활성 네트워크 어댑터에서 추출 (`psutil` 사용 또는 stdlib 조합)

### api.py
DMM API 클라이언트. `httpx.Client` 사용.

```python
class DmmApiClient:
    BASE = "https://apidgp-gameplayer.games.dmm.com"
    HEADERS = {
        "client-app": "DMMGamePlayer5",
        "client-version": "5.4.8",
        "user-agent": "DMMGamePlayer5-Win/5.4.8 Electron/34.3.0",
        # ... 기타
    }

    def get_login_url(self) -> str: ...
    def issue_token(self, code: str) -> str: ...
    def check_token(self, token: str) -> bool: ...
    def launch_game(self, token: str, product_id: str,
                    game_type: str, hwid: HardwareIds) -> LaunchResponse: ...
    def get_filelist(self, token: str, file_list_url: str) -> tuple[list[FileEntry], str]:
        """returns (entries, cdn_domain)"""
        ...
```

- 모든 메서드에 **3회 재시도 + 지수 백오프** (httpx의 transport retry 또는 직접 구현)
- 네트워크 에러는 `DmmApiError`로 래핑
- 토큰 만료(`check_token == False`)는 정상 반환, 발급 실패는 예외

### verify.py
병렬 MD5 검증.

```python
@dataclass
class VerificationResult:
    file: FileEntry
    needs_download: bool
    reason: str | None  # 'missing', 'size_mismatch', 'hash_mismatch', None

def verify_files(
    entries: list[FileEntry],
    base_dir: Path,
    max_workers: int = 8,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[VerificationResult]: ...
```

- `concurrent.futures.ThreadPoolExecutor` 사용
- progress_cb는 (완료된 개수, 총 개수)
- 빈 파일이나 권한 에러는 `needs_download=True, reason='unreadable'`

### download.py
진행률 콜백 다운로더.

```python
@dataclass
class DownloadProgress:
    bytes_received: int
    total_bytes: int | None  # None이면 unknown
    file_name: str

def download_file(
    url: str,
    destination: Path,
    cookie: str | None = None,
    progress_cb: Callable[[DownloadProgress], None] | None = None,
    chunk_size: int = 81920,
) -> None: ...
```

- httpx 스트리밍 (`client.stream("GET", url)`)
- 부모 디렉토리 자동 생성
- 다운로드 실패 시 부분 파일 삭제 후 예외 전파
- 3회 재시도 (이건 호출자가 결정해도 됨)

## 테스트

`tests/` 아래에:

### test_dmmcfg.py
- `tests/fixtures/dmmgame.cnf.sample`을 파싱해서 5개 게임이 나오는지
- 각 필드가 정확히 매핑되는지

### test_api.py
- `pytest-httpx`로 모킹
- `issue_token`, `check_token`, `launch_game`이 올바른 페이로드를 보내는지
- 재시도 동작 (5xx 응답 → 재시도 → 성공)
- `DmmApiError` 발생 케이스

### test_verify.py
- 임시 디렉토리에 파일 생성 후 검증
- 누락/크기불일치/해시불일치 각 케이스

### test_download.py
- httpx mock으로 진행률 콜백이 호출되는지
- 실패 시 부분 파일이 삭제되는지

## 검증
- `pytest -v` → 모든 테스트 pass
- `mypy src/` → 0 errors
- `ruff check src/ tests/` → clean

## 주의
- 이 단계는 **순수 비즈니스 로직만**. PyQt 의존성 금지.
- store/, gui/는 건드리지 마라.
- known_games.json도 아직 안 채움.
