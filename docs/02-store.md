# DMM Launcher: Store 레이어 구현

## 사전 조건
프롬프트 1까지 완료. core/ 레이어가 모두 동작하고 테스트 통과.

## 이 단계의 산출물

### store/paths.py
```python
def get_app_data_dir() -> Path:  # %APPDATA%\dmm-launcher
def get_profiles_path() -> Path
def get_games_path() -> Path
def get_logs_dir() -> Path
def get_known_games_path() -> Path  # 패키지 내 resources/known_games.json
```

- 디렉토리는 호출 시 자동 생성

### store/profiles.py
프로필 CRUD. JSON 파일 기반.

```python
@dataclass
class Profile:
    id: str          # uuid4
    name: str
    token: str | None
    created_at: datetime
    last_used_at: datetime | None

class ProfileStore:
    def __init__(self, path: Path): ...
    def list(self) -> list[Profile]: ...
    def get(self, profile_id: str) -> Profile | None: ...
    def create(self, name: str) -> Profile: ...
    def update(self, profile: Profile) -> None: ...
    def delete(self, profile_id: str) -> None: ...
    def get_default(self) -> Profile | None: ...
    def set_default(self, profile_id: str) -> None: ...
```

- 파일 형식:
  ```json
  {
    "version": 1,
    "default_profile_id": "uuid-...",
    "profiles": [...]
  }
  ```
- 동시 쓰기 방지: 임시 파일에 쓰고 `os.replace()`로 원자적 교체
- 토큰은 평문 저장 (Windows DPAPI 통합은 향후 작업)

### store/games.py
사용자가 설정한 게임 정보 (exe 경로, 프로필 할당 등).

```python
@dataclass
class GameConfig:
    product_id: str
    exe_path: Path | None       # None이면 미설정
    profile_id: str | None      # None이면 기본 프로필 사용
    favorite: bool = False
    last_played_at: datetime | None = None

class GameStore:
    def __init__(self, path: Path): ...
    def list(self) -> list[GameConfig]: ...
    def get(self, product_id: str) -> GameConfig | None: ...
    def upsert(self, config: GameConfig) -> None: ...
    def delete(self, product_id: str) -> None: ...
```

### store/known_games.py
사전 등록 게임 메타데이터 로더 (읽기 전용).

```python
@dataclass(frozen=True)
class KnownGame:
    product_id: str
    display_name: str
    exe_name_candidates: list[str]
    tags: list[str]
    icon_url: str | None

def load_known_games() -> dict[str, KnownGame]:
    """resources/known_games.json 읽음"""
```

### resources/known_games.json
dmmgame.cnf.sample에 있던 5개 게임을 채운다. exe_name_candidates는
- `tskx`: `["twinkle_starknightsx.exe"]`
- 나머지 4개는 `[]`로 두거나 productId 기반 추측 (예: `muv_luv_girlsgardenx_cl` → `["girlsgardenx.exe", "muv_luv_girlsgardenx.exe"]`)

```json
{
  "games": {
    "tskx": {
      "displayName": "Twinkle☆Star Knights X",
      "exeNameCandidates": ["twinkle_starknightsx.exe"],
      "tags": ["RPG", "Action"],
      "iconUrl": null
    },
    "muv_luv_girlsgardenx_cl": { ... },
    "dotabyss_x_cl": { ... },
    "girlscreation_r": { ... },
    "rlyehshoujotaix_cl": { ... }
  }
}
```

## 테스트

### test_profiles.py
- 빈 store에서 생성 → 조회 → 갱신 → 삭제
- `set_default` 동작
- 동시 쓰기 시 파일 손상 없음 (간단히 두 번 연속 저장)
- 잘못된 JSON 파일이면 백업하고 새로 시작

### test_games.py
- upsert 신규/기존
- 미설정 (exe_path=None) 게임 처리

### test_known_games.py
- 5개 게임 모두 로드되는지

## 검증
- `pytest -v` 모두 pass
- `mypy src/` clean

## 주의
- gui/ 건드리지 마라
- 향후 토큰 암호화 확장 가능하게 ProfileStore 인터페이스를 추상화 가능하면 좋음 (필수 아님)
