# DMM Launcher: GUI 레이어 구현

## 사전 조건
프롬프트 2까지 완료. core/, store/ 모두 테스트 통과.

## 이 단계의 산출물

### gui/main_window.py
앱 메인 창. 게임 카드 그리드 표시.

레이아웃:
```
┌────────────────────────────────────────────┐
│  DMM Launcher          [프로필 관리] [설정] │
├────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐         │
│  │  TSK X │ │ MuvLuv │ │DotAbyss│   ...   │
│  │ [Main] │ │ [Sub ] │ │ [Main] │         │
│  │ ▶ 실행 │ │ ⚙ 설정 │ │ ▶ 실행 │         │
│  └────────┘ └────────┘ └────────┘         │
└────────────────────────────────────────────┘
```

동작:
- 시작 시 `dmmgame.cnf` 자동 스캔 → 설치된 게임 목록 추출
- known_games + games.json 머지해서 카드 표시
- 미설정 카드 클릭 → 설정 마법사
- 설정된 카드 클릭 → 실행 흐름

**중요**: `dmmgame.cnf`가 게임 목록의 **단일 진실의 출처(SSOT)**다.
- 사용자가 임의의 게임을 추가하는 기능은 **만들지 않는다**.
- 이유: 게임 클라이언트 파일은 DMM 런처가 사전에 다운로드해야만 동작하므로,
  cnf에 등록되지 않은 게임은 어차피 launch API가 거부함.
- DMM 런처에서 게임을 새로 설치하면 cnf에 자동 추가 → 다음 앱 시작 시 카드로 나타남.
- 앱은 cnf를 **읽기 전용**으로만 사용한다. 절대 쓰지 마라.

### gui/game_card.py
개별 게임 카드 위젯 (`QFrame` 기반).
- 게임명 (display_name 또는 product_id)
- 할당된 프로필 이름 (없으면 "기본 프로필")
- 상태 배지: ⚙ 설정 필요 / ▶ 실행 가능
- 클릭/우클릭 메뉴 (실행, 설정, 프로필 변경, 강제 검증, 등)

### gui/setup_wizard.py
미설정 게임 설정 마법사 (`QWizard`).

페이지:
1. **소개**: "이 게임을 설정합니다: {게임명}"
2. **exe 선택**:
   - 자동 탐지 결과 표시 (known_games의 후보로 install_path/ 안에서 검색)
   - 후보가 있으면 "이 파일이 맞나요? [예/아니요]"
   - 직접 선택 버튼 (`QFileDialog`, install_path를 시작 경로로)
3. **프로필 선택**:
   - 콤보박스로 기존 프로필 선택
   - 또는 "신규 프로필 생성" 버튼
4. **완료**: games.json에 저장

### gui/profile_dialog.py
프로필 관리 창.
- 프로필 목록 (이름, 토큰 상태(유효/만료/없음), 마지막 사용)
- 추가 / 이름변경 / 삭제 / 기본 설정
- "토큰 발급" 버튼 → login_dialog 호출

### gui/login_dialog.py
QtWebEngine 기반 로그인 창. **이게 핵심 UX 차별점**.

흐름:
1. `DmmApiClient.get_login_url()` 호출
2. `QWebEngineView`에 URL 로드
3. URL 변경 이벤트 감시:
   - `?code=...` 파라미터가 보이면 → 추출 후 창 닫음
   - 또는 redirect_uri로 이동 시도하면 가로챔
4. `issue_token(code)` → 프로필에 저장

```python
class LoginDialog(QDialog):
    token_issued = pyqtSignal(str)  # 발급된 토큰

    def __init__(self, api: DmmApiClient, parent=None): ...
```

**주의**: redirect_uri가 `dmmgameplayer5://` 같은 커스텀 스킴이라
QtWebEngine이 자동으로 처리 못 할 수 있음. `urlChanged` 시그널에서
URL 문자열 자체를 검사해서 `code` 파라미터를 잡아라.
브라우저 내부 네비게이션을 막을 필요는 없고, code만 캡처하면 됨.

### gui/progress_dialog.py
다운로드/검증 진행 다이얼로그.
- 두 단계 표시: "검증 중 (X/Y)" → "다운로드 중 (X/Y, NN%)"
- 취소 버튼 (`QThread.requestInterruption`)
- 모달 (앱 메인 차단)

### gui/workers.py
백그라운드 작업 (모두 `QThread` 또는 `QObject` + `moveToThread` 패턴).

```python
class LaunchWorker(QObject):
    """게임 실행 전체 흐름 (검증 → 다운로드 → exe 실행)"""
    progress = pyqtSignal(str, int, int)  # message, current, total
    finished = pyqtSignal(bool, str)      # success, message

    def run(self): ...

class TokenCheckWorker(QObject):
    """토큰 유효성 비동기 확인"""
    ...
```

### __main__.py 갱신
- ProfileStore, GameStore 초기화
- DmmApiClient 인스턴스 생성
- MainWindow 생성 후 표시
- 첫 실행 감지 (프로필 없음) → 자동으로 ProfileDialog 띄우기

## 테스트

`pytest-qt`로 GUI 테스트:

### test_main_window.py
- `dmmgame.cnf` 모킹해서 5개 카드 렌더링 확인
- 미설정 카드는 "설정 필요" 배지
- 설정된 카드는 "실행 가능" 배지

### test_setup_wizard.py
- 마법사 페이지 흐름
- exe 자동 탐지 (임시 폴더에 가짜 exe 생성)
- 완료 시 GameStore에 저장되는지

### test_login_dialog.py
- 모킹된 URL 변경 이벤트로 code 추출 시그널 발생 확인
- (실제 웹뷰 로딩은 통합 테스트로 분리)

## 검증
- `python -m dmm_launcher` 실행 시:
  1. 프로필 없으면 ProfileDialog 자동 표시
  2. dmmgame.cnf의 5개 게임이 카드로 보임
  3. 미설정 카드 클릭 → 마법사
  4. 설정 후 실행 클릭 → (실제 게임 실행은 토큰 있어야 함)
- `pytest -v` 통과 (qt 테스트 포함)

## 주의
- 모든 네트워크 호출은 워커 스레드. UI 스레드 블록 금지.
- 에러는 `QMessageBox.critical`로 사용자에게 표시. 절대 silent fail 금지.
- `qInstallMessageHandler`로 Qt 경고도 로그에 남기기.
