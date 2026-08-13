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

- Python 3.9 이상
- `requirements.txt`에 명시된 `requests`, `questionary` 등의 라이브러리

## 설치 방법 (Installation)

아래 두 줄만 실행합니다:

```bash
venv/bin/pip install -r requirements.txt
venv/bin/python main.py
```

## 실행 및 초기 설정 (Setup & First Run)

1. **첫 실행 자격 증명 등록**

`main.py`를 첫 실행하면 자격 증명을 입력받고 즉시 SSO 로그인으로 검증한 뒤, 검증에 성공해야만 로컬 저장합니다.

```text
포털 ID: 입력
포털 비밀번호: 비밀번호는 입력 시 화면에 표시되지 않습니다.
```

로그인 실패 시에는 어떤 파일도 쓰지 않습니다. 로그인 성공 시 `credentials.enc`가 생성되고, 다음 실행부터는 로그인해서 저장된 자격 증명을 자동으로 사용합니다.

2. **기존 파일 마이그레이션**

루트의 `secrets.json`이 남아 있으면(이전 버전에서 사용하던 방식), 자동으로 인증을 시도 후 성공 시 로컬 안전 저장소로 이전합니다.
이동이 완료되면 수동으로 `secrets.json` 삭제를 권장합니다.

## 사용 방법 (Usage)

항상 다음 명령으로 실행합니다:

```bash
venv/bin/python main.py
```

실행 흐름:

1. 저장된 자격 증명 자동 로드(있으면) 또는 ID/비밀번호 입력 및 첫 실행 검증.
2. 포털 희망수업 조회.
3. 신청 과목 다중선택 및 우선순위 지정.
4. 실행 모드 선택:
   - `예약 수강신청`(기본값): 오늘 날짜 `09:00:00`에서 시작하는 날짜·시간 선택기를 표시.
     - `←/→`로 연·월·일·시·분·초 항목을 이동하고 `↑/↓`로 값을 변경합니다.
     - `Enter`로 확정하고 `Esc` 또는 `Ctrl+C`로 취소합니다. 과거 시각은 확정할 수 없습니다.
     - 대상 시각까지 남은 시간을 같은 터미널 한 줄에 표시하며, 하루 이상이면 `4일 10:10:39`처럼 표시합니다.
     - 도달 시 과목별 1회씩만 시도.
     - 실패한 과목만 추려 즉시 `바로 취케팅`으로 전환.
   - `바로 취케팅`: 실패 과목이 없어질 때까지 우선순위 라운드로 무제한 반복.
5. 카운트다운 중 `Ctrl+C`를 누르면 신청 요청 없이 안전하게 종료합니다. 신청 중 중단하면 완료/대기 상태 요약을 출력합니다.

## 보안 주의 (Security)

저장된 비밀번호는 Fernet으로 암호화되어 `credentials.enc`에 저장되며, 변조 시 복호화 검증 실패로 즉시 차단됩니다.
단, 공격자가 `credential.key`와 `credentials.enc` 두 파일 모두 탈취하면 복호화가 가능하므로, 두 파일 모두 동일 기기/계정의 권한 경계 내에서 보호해야 합니다.

저장 위치는 플랫폼별로 달라지며 `platformdirs`가 다음 규칙으로 계산합니다.
- 키: `platformdirs.user_config_path("hyu-course-registration", appauthor=False) / "credential.key"`
- 토큰: `platformdirs.user_data_path("hyu-course-registration", appauthor=False) / "credentials.enc"`

예시:
- Linux: `~/.config/hyu-course-registration/credential.key`, `~/.local/share/hyu-course-registration/credentials.enc`
- macOS: `~/Library/Application Support/hyu-course-registration/credential.key`, `~/Library/Application Support/hyu-course-registration/credentials.enc`
- Windows: `%APPDATA%`/`%LOCALAPPDATA%` 기반 `platformdirs` 표준 경로

## 면책 조항 (Disclaimer)

이 프로그램을 사용하여 발생하는 모든 결과(계정 정지, 불이익 등)에 대한 책임은 전적으로 사용자 본인에게 있습니다.
