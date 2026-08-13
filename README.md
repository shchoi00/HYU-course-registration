# 한양대학교 수강신청 자동화 (Hanyang University Course Registration Automation)

한양대학교 수강신청 시스템을 위한 자동화 스크립트입니다. RSA 암호화된 SSO 로그인, NetFunnel 대기열 관리, 그리고 자동 수강신청 기능을 지원합니다.

## 주요 기능 (Features)

- **SSO 로그인**: RSA 암호화 방식을 사용하여 자동으로 로그인합니다.
- **NetFunnel 우회**: 대기열 티켓을 자동으로 발급받고 활성화합니다 (Opcode 5001 -> 5002).
- **희망수업 자동 조회**: 포털에 등록한 희망수업을 실행 시 자동으로 불러옵니다.
- **대화형 과목 선택**: 터미널 체크박스로 신청 과목과 우선순위를 선택합니다.
- **우선순위 순회**: 매 라운드마다 1순위부터 각 과목을 한 번씩 신청합니다.
- **스케줄링**: 수강신청 시작 시간까지 대기하다가 정시에 실행됩니다.
- **자동 재시도**: 신청 실패 시 설정된 간격으로 자동으로 재시도합니다.

## 사전 요구 사항 (Prerequisites)

- Python 3.9 이상
- `requirements.txt`에 명시된 `requests`, `questionary` 등의 라이브러리

## 설치 방법 (Installation)

1. 저장소를 클론합니다:

   ```bash
   git clone -
   cd hanyang-sugang-macro
   ```

2. 가상 환경을 생성하고 활성화합니다:

   ```bash
   python -m venv venv
   source venv/bin/activate  # Mac/Linux
   # venv\Scripts\activate  # Windows
   ```

3. 필요한 라이브러리를 설치합니다:
   ```bash
   pip install -r requirements.txt
   ```

## 설정 (Configuration)

1. **계정 설정 (Secrets Setup)**:
   `secrets.json.example` 파일을 `secrets.json`으로 복사한 후, 포털 ID와 비밀번호를 입력하세요.

   ```bash
   cp secrets.json.example secrets.json
   ```

   ```json
   {
     "user_id": "your_id",
     "password": "your_password"
   }
   ```

   _주의: `secrets.json` 파일은 개인 정보를 포함하고 있으므로 git에 커밋되지 않도록 `.gitignore`에 포함되어 있습니다._

2. **실행 설정 (Runtime Setup)**:
   `config.json.example` 파일을 `config.json`으로 복사한 후, 예약 시간과 재시도 정책을 설정하세요. 신청 과목은 파일에 입력하지 않습니다.
   ```bash
   cp config.json.example config.json
   ```
   ```json
   {
     "login_mode": "sso",
     "schedule": {
       "enabled": true,
       "start_time": "2026-02-10 10:00:00"
     },
     "retry": {
       "max_attempts": 50,
       "interval_seconds": 0.3
     }
   }
   ```

## 사용 방법 (Usage)

스크립트를 실행합니다:

```bash
python main.py
```

실행하면 다음 순서로 진행됩니다:

1. `secrets.json`의 포털 계정으로 로그인합니다.
2. 포털의 희망수업 목록을 자동으로 불러옵니다.
3. `Space`로 신청할 과목을 선택하고 `Enter`를 누릅니다.
4. 선택한 과목의 1순위, 2순위 순서를 지정합니다.
5. 각 라운드에서 우선순위 순으로 과목별 한 번씩 신청합니다. 성공한 과목은 다음 라운드에서 제외됩니다.

## 면책 조항 (Disclaimer)

이 프로그램을 사용하여 발생하는 모든 결과(계정 정지, 불이익 등)에 대한 책임은 전적으로 사용자 본인에게 있습니다.
