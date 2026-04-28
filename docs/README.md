# DMM Launcher — Claude Code 작업 가이드

## 진행 순서

다음 순서대로 Claude Code에 프롬프트를 던지세요. **각 단계가 끝나면 검증한 뒤 다음으로 넘어갑니다.**

1. `00-bootstrap.md` — 프로젝트 구조와 의존성 설정
2. `01-core.md` — 비즈니스 로직 (API, MD5 검증, 다운로더) — **`reference-launch-tskx.ps1`도 함께 첨부**
3. `02-store.md` — 프로필/게임 영속성
4. `03-gui.md` — PyQt6 GUI

## 참조 구현

`reference-launch-tskx.ps1`은 동일한 흐름을 PowerShell로 구현한 **검증된 프로토타입**이에요.
01-core 단계에서 CC에 함께 첨부하세요. API 헤더, 페이로드 구조, 인증 흐름의 디테일이
markdown 설명보다 정확합니다.

다만 PS1에는 GUI 앱과 무관한 로직도 섞여 있어요 (자세한 내용은 01-core.md 참고):
- `Test-Pwsh7`, `Switch-ToConsoleMode`, `-Hidden` 스위치 → **무시**
- `Read-Host`로 URL 받는 부분 → **GUI에선 QtWebEngine으로 대체**
- `Get-NetAdapter`로 MAC 추출 → **Python `psutil`로 대체**

핵심만 가져오면 되는 것:
- API 엔드포인트, 헤더, 페이로드 구조 (`Get-AccessToken`, `Get-ValidAccessToken`, `Main` 함수)
- MD5 검증 로직 (`Test-GameFiles`)
- 스트리밍 다운로드 + 진행률 (`Save-FileWithProgress`)

## 각 단계 후 검증할 것

```bash
# 단계 0
uv sync && python -m dmm_launcher  # 빈 창 뜨는지

# 단계 1, 2
pytest -v
mypy src/
ruff check src/ tests/

# 단계 3
python -m dmm_launcher  # 실제 GUI 동작 확인
pytest -v  # qt 테스트 포함
```

## CC에 던질 때 팁

- **한 프롬프트씩** 던지고, 그 단계 결과물을 검증한 뒤 다음으로
- CC가 막히면 "현재 디렉토리 구조 보여달라" 또는 "방금 작성한 파일들 보여달라"로 상태 확인
- 테스트 실패하면 그 출력을 그대로 CC에 붙여넣고 "이 테스트 통과시켜라"

## 작업 완료 후 다음 단계 (이 문서 범위 밖)

- **PyInstaller로 단일 exe 빌드**
- **Windows DPAPI로 토큰 암호화** (현재는 평문 저장)
- **자체 업데이트 기능**
- **시작 메뉴 바로가기 자동 생성** (PowerShell 프로토타입의 install-shortcut.ps1과 유사한 기능)
- **다국어** (한/영/일)

## 알려진 위험 요소

- **redirect_uri 스킴**: DMM OAuth가 `dmmgameplayer5://` 같은 커스텀 스킴을 쓸 수 있는데,
  이 경우 QtWebEngine에서 자동 네비게이션이 막힐 수 있음. `urlChanged` 시그널로 URL 문자열을
  감시해서 code 파라미터를 잡는 방식이 가장 안정적.
- **HWID 더미값**: 현재 hdd_serial/motherboard는 빈 문자열의 SHA256 해시(즉, 모든 사용자가 동일).
  DMM이 향후 이걸 실제 검증하기 시작하면 깨짐.
- **API 버전 변경**: `client-version: 5.4.8`이 deprecated되면 헤더 갱신 필요.
