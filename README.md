# 판자촌 (Shantytown)

DMM Game Player 대체 런처입니다. 게임마다 다른 DMM 계정(프로필)을 지정해서 실행할 수 있습니다.  
이미 설치된 DMM 게임은 일본 국외에서도 VPN 없이 실행할 수 있습니다.

## 기능

- 프로필별 DMM 계정 분리 보관
- `dmmgame.cnf` 파싱해서 설치된 게임 자동 표시
- 비-일본 IP에서도 API 호출 가능
- 외부 브라우저 로그인 + 클립보드 자동 인식
- 토큰을 DPAPI로 암호화해서 저장 (Windows 한정)
- 라이트 / 다크 / 시스템 테마, 한국어 / 영어 UI
- 단일 exe 배포

## 실행법

Release 탭에서 최신 버전의 `shantytown.exe`를 다운로드해서 실행하시면 됩니다.

게임은 미리 공식 DMM Game Player로 설치되어 있어야 합니다. 이 앱은 이미 설치된 게임의 실행만 담당합니다.

## 튜토리얼

앱 첫 실행 시 표시되는 안내와 동일한 내용입니다.

1. 필요한 게임을 DMM Game Player에서 설치합니다. (다운로드 시 VPN이 필요할 수 있습니다.)
2. 사용할 DMM 계정별로 프로필을 생성합니다.
3. PC에 설치된 게임은 자동으로 메인 화면에 표시됩니다.
4. 게임 카드를 클릭하면 실행됩니다. 프로필을 바꾸면 같은 게임을 다른 DMM 계정으로 실행할 수 있습니다.
5. 처음 그 프로필로 게임을 실행하거나 토큰이 만료되면 브라우저로 DMM 로그인을 진행합니다. (로그인 시 VPN이 필요할 수 있습니다.)

---
## 개발 환경

Python 3.11 이상, [`uv`](https://docs.astral.sh/uv/) 권장.

```bash
git clone <repo-url>
cd shantytown
uv sync
uv run python -m shantytown
```

## 테스트 / 타입체크 / 린트

```bash
uv run pytest -v
uv run mypy src/
uv run ruff check src/ tests/
```

## exe 빌드

```bash
uv sync
uv run python scripts/build_exe.py
# → dist/shantytown.exe
```

`app_icon.svg`를 multi-resolution `.ico`로 변환한 뒤 PyInstaller `--onefile --windowed`로 빌드합니다. 결과물은 약 42 MB이고 자체 포함입니다.

## CLI 인자

| 인자 | 동작 |
| --- | --- |
| `--debug` | 에러 발생 시 응답 본문 등 자세한 정보를 표시합니다. telemetry hook도 함께 활성화됩니다. |
| `--locale=ko` / `--locale=en` | UI 언어를 강제합니다. 미지정 시 시스템 로케일을 자동 감지합니다. |
| `--show-tutorial` | 첫 실행 튜토리얼을 강제로 표시합니다. (저장된 플래그는 변경하지 않습니다.) |

나머지 인자는 Qt에 그대로 전달됩니다 (예: `-platform offscreen`).

## 프로젝트 구조

```
src/shantytown/
  core/        # Qt 없는 순수 로직: API 클라이언트, MD5 검증, 다운로더,
               #  DPAPI 래퍼, telemetry, 로케일 감지
  store/       # JSON 영속 저장: 프로필 / 게임 설정 / 앱 설정 / known_games
  gui/         # PyQt6 화면: 메인 윈도우, 카드, 다이얼로그(로그인/프로필/
               #  게임설정/튜토리얼/진행), 워커, 테마
  resources/   # 번들 리소스: Fluent UI 아이콘, 튜토리얼 PNG, 앱 아이콘 SVG
tests/         # 165개 테스트
scripts/       # build_exe.py
docs/          # 초기 PowerShell 프로토타입 + 스프린트 계획
```

## 주의

- 이 앱은 공식 채널이 아닌 방식으로 게임을 실행합니다. 사용에 따른 책임은 사용자에게 있습니다.

---

이 프로젝트의 전체 소스코드와 README까지 모두 저 [Claude Code](https://claude.com/claude-code)로 작성했습니다.  
466줄짜리 PowerShell 프로토타입 하나에서 시작해서 GUI / i18n / DPAPI / exe 빌드 / 165개 테스트까지 채팅 창 하나에서 만들어졌습니다. 인간이 한 일은 대체로 "이 색 별로", "여기서 크래시남", "다음 스프린트 가자" 같은 피드백 정도였습니다.

