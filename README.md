# 한양대학교 수강신청 자동화 (Hanyang University Course Registration Automation)

한양대학교 수강신청 시스템을 위한 자동화 스크립트입니다. RSA 암호화된 SSO 로그인, NetFunnel 대기열 관리, 그리고 자동 수강신청 기능을 지원합니다.

## 주요 기능 (Features)

- **SSO 로그인**: RSA 암호화 방식을 사용하여 자동으로 로그인합니다.
- **NetFunnel 우회**: 대기열 티켓을 자동으로 발급받고 활성화합니다 (Opcode 5001 -> 5002).
- **희망수업 자동 조회**: 포털에 등록한 희망수업을 실행 시 자동으로 불러옵니다.
- **대화형 과목 선택**: 터미널 체크박스로 신청 과목과 우선순위를 선택합니다.
- **예약 수강신청**: 방향키 날짜·시간 선택기로 시작 시각을 정한 뒤 과목별로 정확히 한 번씩 신청하고 실패 과목만 남겨둡니다.
- **바로 취케팅**: 실패 과목이 없어질 때까지 무제한 라운드로 순회 신청합니다.
- **자동 재시도**: NetFunnel/수강신청 오류를 교차 재시도하며 실패한 과목만 다음 라운드에 남깁니다.

## 사전 요구 사항 (Prerequisites)

- Git
- Python 3.9 이상
- 방향키 입력과 한 줄 갱신을 지원하는 일반 터미널

## 설치 방법 (Installation)

### macOS / Linux

```bash
git clone https://github.com/shchoi00/HYU-course-registration.git
cd HYU-course-registration
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
venv/bin/python main.py
```

### Windows PowerShell

```powershell
git clone https://github.com/shchoi00/HYU-course-registration.git
cd HYU-course-registration
py -3.9 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

설치가 끝난 뒤에는 매번 패키지를 다시 설치할 필요 없이 마지막 실행 명령만 사용하면 됩니다.

## 실행 및 초기 설정 (Setup & First Run)

### 첫 실행 자격 증명 등록

별도의 `config.json`이나 인증 파일을 직접 만들 필요가 없습니다. 첫 실행 시 포털 ID와 비밀번호를 입력받아 실제 SSO 로그인을 검증하고, 성공한 경우에만 암호화하여 저장합니다.

```text
포털 ID: 입력
포털 비밀번호: 비밀번호는 입력 시 화면에 표시되지 않습니다.
```

로그인에 실패하면 저장하지 않고 다시 입력받습니다. 성공한 뒤에는 저장된 자격 증명으로 자동 로그인하므로 매번 ID와 비밀번호를 입력하지 않아도 됩니다.

### 이전 버전의 `secrets.json` 마이그레이션

저장소 루트에 기존 `secrets.json`이 있으면 해당 정보로 로그인을 검증한 뒤 암호화 저장소로 이전합니다. 이전 성공 안내가 나오면 평문 `secrets.json`은 삭제하는 것을 권장합니다.

## 사용 방법 (Usage)

### 실행

macOS/Linux:

```bash
venv/bin/python main.py
```

Windows PowerShell:

```powershell
.\venv\Scripts\python.exe main.py
```

### 과목 선택과 우선순위

1. 로그인 후 포털의 희망수업 전체를 자동으로 조회합니다.
2. 체크박스에서 `Space`로 신청할 과목을 선택하고 `Enter`로 완료합니다.
3. 선택한 과목을 대상으로 1순위부터 차례대로 지정합니다.
4. 같은 학수번호의 분반은 수업번호로 구분하여 표시됩니다.

프로그램이 사용하는 목록은 포털의 희망수업 목록이므로 별도의 과목 파일을 선택하거나 수정할 필요가 없습니다.

### 예약 수강신청

모드 선택 화면에서 `예약 수강신청`을 선택합니다. 날짜·시간 선택기는 오늘 날짜의 `09:00:00`에서 시작하며 처음에는 `일` 항목이 선택되어 있습니다.

```text
예약 시각: [2026]-[08]-[14]  [09]:[00]:[00]
                    ▲
←/→ 항목 이동   ↑/↓ 값 변경   Enter 확정   Esc 취소
```

- `←/→`: 연·월·일·시·분·초 항목 이동
- `↑/↓`: 선택한 값 변경
- `Enter`: 미래 시각을 확정하고 카운트다운 시작
- `Esc` 또는 `Ctrl+C`: 예약 취소

과거 시각은 확정되지 않으며 선택기 안에 경고가 표시됩니다. 월과 일을 변경할 때 말일·윤년·연도 경계를 자동으로 처리합니다.

카운트다운은 새 로그를 계속 만들지 않고 같은 터미널 한 줄만 갱신합니다. 하루 이상 남은 경우 `4일 10:10:39`처럼 표시합니다. 지정 시각이 되면 우선순위 순서로 각 과목을 정확히 한 번씩 신청하며, 실패한 과목만 즉시 취케팅 모드로 넘어갑니다.

### 바로 취케팅

모드 선택 화면에서 `바로 취케팅`을 선택하면 예약 대기 없이 바로 시작합니다. 우선순위 순서로 과목을 한 번씩 순회하고, 성공한 과목은 목록에서 제거하며 실패한 과목만 계속 반복합니다.

### 중단

- 카운트다운 중 `Ctrl+C`: 신청 요청을 보내지 않고 종료
- 신청 중 `Ctrl+C`: 이미 완료된 과목과 아직 대기 중인 과목을 요약하고 종료

## 전체 실행 흐름

1. 저장된 자격 증명 자동 로드(있으면) 또는 ID/비밀번호 입력 및 첫 실행 검증.
2. 포털 희망수업 조회.
3. 신청 과목 다중선택 및 우선순위 지정.
4. 실행 모드 선택:
   - `예약 수강신청`: 지정 시각까지 대기한 뒤 우선순위대로 과목별 1회 시도.
     - 실패한 과목만 추려 즉시 `바로 취케팅`으로 전환.
   - `바로 취케팅`: 실패 과목이 없어질 때까지 우선순위 라운드로 무제한 반복.
5. 카운트다운 중 `Ctrl+C`를 누르면 신청 요청 없이 안전하게 종료합니다. 신청 중 중단하면 완료/대기 상태 요약을 출력합니다.

## 보안 주의 (Security)

저장된 비밀번호는 Fernet으로 암호화되어 `credentials.enc`에 저장되며, 변조 시 복호화 검증 실패로 즉시 차단됩니다.
단, 공격자가 `credential.key`와 `credentials.enc` 두 파일 모두 탈취하면 복호화가 가능하므로, 두 파일 모두 동일 기기/계정의 권한 경계 내에서 보호해야 합니다.

`config.json`, `secrets.json`, `credential.key`, `credentials.enc`, `.env` 계열 파일은 `.gitignore`로 차단됩니다. 현재 인증 키와 암호화 파일은 애초에 Git 저장소 밖의 운영체제별 사용자 디렉터리에 저장됩니다.

저장 위치는 플랫폼별로 달라지며 `platformdirs`가 다음 규칙으로 계산합니다.
- 키: `platformdirs.user_config_path("hyu-course-registration", appauthor=False) / "credential.key"`
- 토큰: `platformdirs.user_data_path("hyu-course-registration", appauthor=False) / "credentials.enc"`

예시:
- Linux: `~/.config/hyu-course-registration/credential.key`, `~/.local/share/hyu-course-registration/credentials.enc`
- macOS: `~/Library/Application Support/hyu-course-registration/credential.key`, `~/Library/Application Support/hyu-course-registration/credentials.enc`
- Windows: `%APPDATA%`/`%LOCALAPPDATA%` 기반 `platformdirs` 표준 경로

## 문제 해결 (Troubleshooting)

- `ModuleNotFoundError`가 나오면 가상환경의 Python으로 `-m pip install -r requirements.txt`를 다시 실행합니다.
- 방향키 선택기가 나타나지 않으면 IDE 출력 창이나 리다이렉션 환경이 아니라 실제 터미널에서 실행합니다.
- 저장된 인증 정보가 손상되면 프로그램이 경고한 뒤 새 ID와 비밀번호를 입력받습니다. 새 로그인 검증이 성공하기 전에는 기존 파일을 덮어쓰지 않습니다.
- 희망수업이 표시되지 않으면 한양대학교 포털에서 희망수업 목록을 먼저 등록한 뒤 다시 실행합니다.

## 면책 조항 (Disclaimer)

이 프로그램을 사용하여 발생하는 모든 결과(계정 정지, 불이익 등)에 대한 책임은 전적으로 사용자 본인에게 있습니다.
