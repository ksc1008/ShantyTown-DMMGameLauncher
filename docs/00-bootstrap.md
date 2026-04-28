# DMM Launcher 프로젝트 부트스트랩

## 목적
DMM Game Player 우회 런처를 PyQt6로 만든다. 핵심 차별화 기능은 **게임별로 다른 DMM 계정(프로필) 사용**이다.

## 배경
DMM Game Player는 Electron 기반의 공식 런처인데, 한 번에 한 계정만 로그인 가능하다. 이 앱은 그 제약을 우회해서 게임마다 다른 계정으로 토큰을 따로 관리할 수 있게 한다.

기존 PowerShell 프로토타입의 핵심 흐름은 다음과 같다 (이걸 Python으로 재구현):

1. OAuth로 access_token 발급/검증 (`/v5/auth/*`)
2. `/v5/r2/launch/cl`로 게임 실행 권한 + CDN 서명 받기
3. 파일 목록 GET 후 로컬 MD5 비교 → 누락/손상만 다운로드
4. `execute_args`로 게임 exe 실행

## 이 단계의 산출물

1. **프로젝트 구조 생성**
   ```
   dmm-launcher/
   ├── pyproject.toml          # uv 또는 hatch 기반
   ├── README.md
   ├── .gitignore
   ├── src/dmm_launcher/
   │   ├── __init__.py
   │   ├── __main__.py
   │   ├── core/__init__.py
   │   ├── store/__init__.py
   │   ├── gui/__init__.py
   │   └── resources/
   │       └── known_games.json
   └── tests/
       ├── __init__.py
       └── fixtures/
           └── dmmgame.cnf.sample
   ```

2. **의존성** (pyproject.toml):
   - `PyQt6 >= 6.6`
   - `PyQt6-WebEngine >= 6.6`
   - `httpx >= 0.27` (HTTP 클라이언트, 동기/비동기 둘 다 지원)
   - dev: `pytest`, `pytest-qt`, `pytest-httpx`, `ruff`, `mypy`
   - Python 3.11+ 타겟

3. **`__main__.py`**: 임시로 PyQt6 빈 창 하나만 띄우는 코드
4. **README.md**: 프로젝트 개요, 설치, 실행 방법
5. **`tests/fixtures/dmmgame.cnf.sample`**: 아래 내용 그대로 넣기:
   ```json
   {"defaultInstallDir":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games","contents":[{"productId":"muv_luv_girlsgardenx_cl","gameType":"ACL","detail":{"installed":true,"version":"p1.0.33","shortcut":"","path":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\muv_luv_girlsgardenx_cl","keyBindSettingVer":""}},{"productId":"tskx","gameType":"ACL","detail":{"installed":true,"version":"01.02.122","shortcut":"","path":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\Twinkle_StarKnightsX","keyBindSettingVer":""}},{"productId":"dotabyss_x_cl","gameType":"ACL","detail":{"installed":true,"version":"1.0.1","shortcut":"","path":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\dotabyss_x_cl","keyBindSettingVer":""}},{"productId":"girlscreation_r","gameType":"ACL","detail":{"installed":true,"version":"1.5.36","shortcut":"","path":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\girlscreation_r","keyBindSettingVer":""}},{"productId":"rlyehshoujotaix_cl","gameType":"ACL","detail":{"installed":true,"version":"1.0.10","shortcut":"","path":"C:\\Games\\Celestite_Windows_2.0.25071.1\\Games\\rlyehshoujotaix_cl","keyBindSettingVer":""}}]}
   ```

6. **`known_games.json`**: 빈 골격만 (다음 단계에서 채움)
   ```json
   {"games": {}}
   ```

## 검증
- `uv sync` (또는 `pip install -e .[dev]`) 성공
- `python -m dmm_launcher` 실행 시 빈 PyQt6 창이 뜸
- `pytest` 실행 시 0 passed (테스트 파일은 다음 단계에서)

## 주의
- 아직 GUI 본체나 API 코드는 작성하지 마라. 이 단계는 부트스트랩만이다.
- 모든 코드는 type hint와 docstring 포함.
