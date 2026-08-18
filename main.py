#!/usr/bin/env python3
"""한양대학교 수강신청 자동화 시스템"""

import base64
import html as html_lib
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

from credentials import (
    CredentialSetupCancelled,
    CredentialStore,
    default_credential_paths,
    obtain_validated_credentials,
)
from workflow import (
    DateTimePickerState,
    ScheduleValidationError,
    countdown_until,
    parse_target_time,
    run_polling_ticketing,
    run_scheduled_pass,
    run_ticketing,
)

BASE_URL = "https://portal.hanyang.ac.kr/sugang"
NF_SETTING_URL = "https://nf-setting-bucket.stclab.com/hynfad-3391.netfunnel/nf-setting.json"
NF_GATE_URL = "https://hynfad-3391.netfunnel.stclab.com/ts.wseq"

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
}

# AJAX 요청용 헤더 (API 호출 시 사용)
AJAX_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json+sua; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/sulg.do",
    "Origin": BASE_URL,
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


class AuthenticationError(RuntimeError):
    pass


def load_config():
    if not os.path.exists("config.json"):
        config = {}
    else:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)

    if os.path.exists("secrets.json"):
        with open("secrets.json", "r", encoding="utf-8") as f:
            secrets = json.load(f)
            config.update(secrets)
        log(
            "secrets.json 기존 인증 파일이 감지되었습니다. "
            "저장소 마이그레이션 후 삭제를 권장합니다: secrets.json",
            "yellow",
        )

    return config


def log(msg, color=None):
    colors = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m"}
    reset = "\033[0m"
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    prefix = f"[{timestamp}]"
    if color and color in colors:
        print(f"{prefix} {colors[color]}{msg}{reset}")
    else:
        print(f"{prefix} {msg}")


class TicketingPollRenderer:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.active = False

    def __call__(self, poll_number, observations):
        details = []
        for course, status in observations:
            haksu_no = course.get("haksuNo", "?")
            enrolled = course.get("sincheongInwon", "?")
            limit = course.get("jehanInwon", "?")
            if status == "registered":
                detail = f"{haksu_no} 신청확인"
            elif status == "available":
                detail = f"{haksu_no} {enrolled}/{limit} 빈자리"
            elif status == "full":
                detail = f"{haksu_no} {enrolled}/{limit} 만석"
            elif status == "blocked":
                detail = f"{haksu_no} 타분반 신청됨"
            else:
                detail = f"{haksu_no} 조회불명"
            details.append(detail)

        line = f"[취케팅 조회 {poll_number}] " + " | ".join(details)
        self.stream.write(f"\r\033[2K{line}")
        self.stream.flush()
        self.active = True

    def finish(self):
        if self.active:
            self.stream.write("\n")
            self.stream.flush()
            self.active = False


def create_session(config):
    """로그인 모드에 따라 세션을 생성한다."""
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)

    if config.get("login_mode") == "cookie":
        return login_with_cookie(session, config)
    else:
        return login_with_sso(session, config)


def login_with_cookie(session, config):
    """브라우저에서 복사한 쿠키로 세션을 설정한다."""
    cookie_str = config.get("cookie", "")
    if not cookie_str:
        log("config.json의 cookie 필드를 채워주세요.", "red")
        log("브라우저 DevTools > Application > Cookies에서 복사", "yellow")
        raise AuthenticationError("cookie is required")

    # "key=value; key2=value2" 형식 파싱
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            session.cookies.set(name.strip(), value.strip(), domain="portal.hanyang.ac.kr")

    # 세션 검증: sulg.do 접근
    resp = session.get(f"{BASE_URL}/sulg.do", allow_redirects=False)
    if resp.status_code == 302 or "lgins" in resp.text[:500]:
        log("쿠키가 만료되었습니다. 브라우저에서 다시 복사해주세요.", "red")
        raise AuthenticationError("cookie login failed")

    log("쿠키 로그인 성공", "green")
    return session


def rsa_encrypt(plaintext, modulus_hex):
    """한양대 포털의 RSA 암호화를 재현한다.

    enc_core.js의 fnRSAEnc 구현:
    1. 평문을 Base64 인코딩
    2. 50자씩 분할
    3. 각 청크를 RSA PKCS#1 v1.5 (type 2) 암호화
    4. 결과를 hex로 변환 후 연결
    """
    b64_text = base64.b64encode(plaintext.encode()).decode()
    modulus = int(modulus_hex, 16)
    exponent = 0x10001  # 65537
    key_size = (modulus.bit_length() + 7) // 8

    encrypted = ""
    for i in range(0, len(b64_text), 50):
        chunk = b64_text[i:i + 50]
        # PKCS#1 v1.5 type 2 padding
        msg_bytes = chunk.encode()
        padding_len = key_size - len(msg_bytes) - 3
        padding = bytes(b if (b := os.urandom(1)[0]) != 0 else os.urandom(1)[0] for _ in range(padding_len))
        # 패딩에 0x00이 없도록 보장
        padding = b""
        while len(padding) < padding_len:
            b = os.urandom(1)
            if b != b"\x00":
                padding += b
        padded = b"\x00\x02" + padding + b"\x00" + msg_bytes
        # RSA 암호화: m^e mod n
        m = int.from_bytes(padded, "big")
        c = pow(m, exponent, modulus)
        h = format(c, "0" + str(key_size * 2) + "x")
        encrypted += h

    return encrypted


def login_with_sso(session, config):
    """SSO를 통해 자동 로그인한다.

    흐름:
    1. lgins.do 로그인 페이지 접근
    2. publicTk.do로 RSA 공개키 획득
    3. ID/PW를 RSA 암호화
    4. lgnps.do로 암호화된 정보 POST
    """
    user_id = config.get("user_id", "")
    password = config.get("password", "")
    if not user_id or not password:
        log("config.json의 user_id와 password를 채워주세요.", "red")
        raise AuthenticationError("user_id and password are required")

    log("SSO 로그인 시도 중...", "cyan")

    # 1. 로그인 페이지 접근 (세션 쿠키 획득)
    login_url = f"{BASE_URL}/lgins.do?type=pop&returl=https%3A%2F%2Fportal.hanyang.ac.kr%2Fsugang%2Fslgns.do"
    session.get(login_url)

    # 2. RSA 공개키 획득
    key_nm = "sso_002"
    resp = session.post(
        f"{BASE_URL}/publicTk.do",
        json={"keyNm": key_nm, "encStr": user_id},
        headers=AJAX_HEADERS,
    )
    pub_key = resp.json()["key"][0]["value"]
    log(f"RSA 공개키 획득: {pub_key[:32]}...", "cyan")

    # 3. ID/PW RSA 암호화
    enc_user_id = rsa_encrypt(user_id, pub_key)
    enc_password = rsa_encrypt(password, pub_key)

    # 4. lgnps.do로 로그인 요청
    login_data = {
        "loginGb": "1",
        "systemGb": "SUGANG",
        "ipSecGb": "1",
        "returl": f"{BASE_URL}/slgns.do?locale=ko",
        "userId": enc_user_id,
        "password": enc_password,
        "keyNm": key_nm,
    }
    resp = session.post(
        f"{BASE_URL}/lgnps.do",
        data=login_data,
        allow_redirects=True,
    )

    # 5. 로그인 성공 확인: slgns.do 접근
    resp = session.get(f"{BASE_URL}/slgns.do?locale=ko", allow_redirects=True)

    # sulg.do 접근 테스트
    resp = session.get(f"{BASE_URL}/sulg.do", allow_redirects=False)
    if resp.status_code == 302 or "lgins" in resp.text[:500]:
        log("SSO 로그인 실패. 아이디/비밀번호를 확인해주세요.", "red")
        raise AuthenticationError("SSO login failed")

    log("SSO 로그인 성공", "green")
    return session


def extract_tokens(session):
    """sulg.do HTML에서 tk 토큰과 기타 파라미터를 추출한다."""
    token_pattern = r"[A-Za-z0-9._~-]{16,256}"
    document = ""
    tk_match = None
    for path in ("/sulg.do", "/slgns.do?locale=ko"):
        resp = session.get(f"{BASE_URL}{path}")
        document = html_lib.unescape(resp.text)
        document = (
            document.replace("\\u0026", "&")
            .replace("\\x26", "&")
            .replace("\\u003d", "=")
            .replace("\\x3d", "=")
        )
        tk_match = re.search(
            rf"(?:[?&])tk\s*=\s*({token_pattern})",
            document,
            re.IGNORECASE,
        )
        if not tk_match:
            tk_match = re.search(
                rf"\btk\s*[:=]\s*['\"]({token_pattern})['\"]",
                document,
                re.IGNORECASE,
            )
        if tk_match:
            break
    if not tk_match:
        log("tk 토큰을 찾을 수 없습니다.", "red")
        raise AuthenticationError("tk token not found")

    tk = tk_match.group(1)

    # 사용자 정보 추출
    gaein_match = re.search(r'gaeinNo\s*:\s*"(\d+)"', document)
    sosok_match = re.search(r'sosokCd\s*:\s*"([^"]+)"', document)
    info = {
        "tk": tk,
        "pgmId": "P310298",
        "menuId": "M008958",
        "gaeinNo": gaein_match.group(1) if gaein_match else "",
        "sosokCd": sosok_match.group(1) if sosok_match else "",
    }

    log(f"토큰 추출 완료: tk={tk[:16]}...", "green")
    if info["gaeinNo"]:
        log(f"학번: {info['gaeinNo']}", "cyan")

    return info


def get_netfunnel_key(session, segment_key="hyuSgSincheong"):
    """
    NetFunnel 키 발급 (opcode=5001 사용)
    """
    # opcode=5001 (Get Ticket) - 키가 없는 상태에서 최초 발급 요청
    params = {
        "opcode": "5001",
        "key": "",
        "nfid": "0",
        "prefix": f"NetFunnel.gRtype={segment_key};",
        "sid": "service_209",
        "aid": segment_key,
        "js": "yes",
        "qd": "0",
    }

    headers = {
        "Referer": f"{BASE_URL}/",
        "User-Agent": COMMON_HEADERS["User-Agent"],
        "Accept": "*/*",
        "Host": "hynfad-3391.netfunnel.stclab.com",
    }

    try:
        # 1. opcode=5001 (Get Ticket)
        response = session.get(NF_GATE_URL, params=params, headers=headers, timeout=5)

        if response.status_code == 200 and "key=" in response.text:
            key_part = response.text.split("key=")[1]
            key_val = key_part.split("&")[0]
            log(f"NetFunnel 티켓 획득: {key_val[:20]}...", "green")

            # 2. opcode=5002 (Enter Queue / Check In)
            # 획득한 키로 대기열 진입 요청
            params_5002 = {
                "opcode": "5002",
                "key": key_val,
                "nfid": "0",
                "prefix": f"NetFunnel.gRtype={segment_key};",
                "sid": "service_209",
                "aid": segment_key,
                "js": "yes",
                "qd": "0",
            }
            resp_5002 = session.get(NF_GATE_URL, params=params_5002, headers=headers, timeout=5)
            if resp_5002.status_code == 200 and "key=" in resp_5002.text:
                key_part_2 = resp_5002.text.split("key=")[1]
                key_val_2 = key_part_2.split("&")[0]
                log(f"NetFunnel 키 활성화 성공: {key_val_2[:20]}...", "green")
                return key_val_2
            else:
                log(f"NetFunnel 5002 실패: {resp_5002.text[:100]}", "yellow")
                # 5002 실패해도 5001 키가 있으면 일단 반환해봄
                return key_val
        else:
            log(f"NetFunnel 키 발급 실패: {response.text[:100]}", "red")
            return None

    except Exception as e:
        log(f"NetFunnel 요청 중 오류 발생: {e}", "red")
        return None


def release_netfunnel_key(session, key):
    """NetFunnel 키를 해제한다."""
    params = {"opcode": "5004", "key": key}
    try:
        session.get(
            NF_GATE_URL,
            params=params,
            headers={"Referer": "https://portal.hanyang.ac.kr/"},
        )
    except Exception:
        pass


def fetch_course_list(session, tokens, log_result=True):
    """희망수업 목록을 조회한다."""
    url = f"{BASE_URL}/SgscAct/findHeemangSuupSearchs.do?pgmId={tokens['pgmId']}&menuId={tokens['menuId']}&tk={tokens['tk']}"
    data = {"strJojikGb": "2", "strGrade": "3"}

    resp = session.post(url, json=data, headers=AJAX_HEADERS)
    result = resp.json()
    if not isinstance(result, dict):
        raise requests.RequestException("invalid wishlist response")

    courses = []
    ds = result.get("DS_SUUPGG03TTM01", [{}])
    if ds and "list" in ds[0]:
        courses = ds[0]["list"]

    if log_result:
        log(f"희망수업 {len(courses)}개 조회됨", "cyan")
        for c in courses:
            log(f"  {c.get('haksuNo', '?')} - {c.get('gwamokNm', '?')} (수업번호: {c.get('suupNo', '?')})", "cyan")

    return courses


def find_course_info(courses, course_id):
    """학수번호 또는 학수번호+수업번호로 과목 정보를 찾는다.

    Args:
        courses (list): 희망수업 목록
        course_id (str or dict): 검색할 과목 정보
            - str: 학수번호 (예: "COE8042") -> 첫 번째 일치하는 과목 반환
            - dict: {"haksuNo": "COE8042", "suupNo": "30016"} -> 두 조건 모두 일치하는 과목 반환
    """
    target_haksu = ""
    target_suup = ""

    if isinstance(course_id, dict):
        target_haksu = course_id.get("haksuNo", "")
        target_suup = course_id.get("suupNo", "")
    else:
        target_haksu = str(course_id)

    for c in courses:
        # 1. 학수번호 불일치 시 건너뜀
        if c.get("haksuNo") != target_haksu:
            continue

        # 2. 수업번호가 지정된 경우, 수업번호도 일치해야 함
        if target_suup and str(c.get("suupNo")) != str(target_suup):
            continue

        return c

    return None


def order_courses_by_priority(courses, choose_course):
    """선택된 과목을 사용자가 지정한 우선순위로 정렬한다."""
    remaining = list(courses)
    ordered = []

    while len(remaining) > 1:
        priority = len(ordered) + 1
        selected = choose_course(priority, tuple(remaining))
        if selected is None:
            return None
        ordered.append(selected)
        remaining.remove(selected)

    return ordered + remaining


def select_target_courses(courses, questionary_module=None):
    """희망수업에서 신청 대상을 고르고 우선순위를 지정한다."""
    if questionary_module is None:
        import questionary as questionary_module

    def choice(course):
        title = (
            f"{course.get('gwamokNm', '?')} | {course.get('haksuNo', '?')} "
            f"| 수업번호 {course.get('suupNo', '?')}"
        )
        return questionary_module.Choice(title=title, value=course)

    selected = questionary_module.checkbox(
        "신청할 희망수업을 선택하세요 (Space 선택, Enter 완료)",
        choices=[choice(course) for course in courses],
    ).ask()
    if not selected:
        return selected

    def choose_priority(priority, remaining):
        return questionary_module.select(
            f"{priority}순위 과목을 선택하세요",
            choices=[choice(course) for course in remaining],
        ).ask()

    return order_courses_by_priority(selected, choose_priority)


def run_registration_round_robin(
    courses,
    max_attempts,
    attempt_course,
    wait_for_next_round=lambda: None,
    on_attempt_error=None,
):
    """우선순위 순으로 과목별 한 번씩 신청하며 실패 과목만 재시도한다."""
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")

    states = [
        {"course": course, "attempts": 0, "status": None}
        for course in courses
    ]
    pending = list(states)

    while pending:
        next_round = []
        for state in pending:
            state["attempts"] += 1
            try:
                status = attempt_course(state["course"], state["attempts"])
            except requests.RequestException as error:
                if on_attempt_error:
                    on_attempt_error(state["course"], state["attempts"], error)
                status = "retry"

            if status == "retry" and state["attempts"] < max_attempts:
                next_round.append(state)
            elif status == "retry":
                state["status"] = "failed"
            elif status == "success":
                state["status"] = status
            else:
                raise ValueError(f"알 수 없는 신청 상태: {status}")

        pending = next_round
        if pending:
            wait_for_next_round()

    return states


def classify_registration_result(out_code, out_msg):
    """수강신청 응답을 라운드 로빈 실행 상태로 변환한다."""
    if "중복" in out_msg and "신청" in out_msg:
        return "blocked"
    if "이미" in out_msg and "신청" in out_msg:
        return "success"
    if out_code in ("SUCCESS", "S") or "성공" in out_msg or "완료" in out_msg:
        return "success"
    return "retry"


def _parse_nonnegative_count(value):
    if isinstance(value, bool):
        return None
    try:
        count = int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def classify_ticketing_course(course, courses=None):
    """희망수업 조회값으로 신청 여부와 잔여석 상태를 판정한다."""
    registered_count = _parse_nonnegative_count(course.get("sincheongSuupCnt"))
    enrolled_count = _parse_nonnegative_count(course.get("sincheongInwon"))
    limit_count = _parse_nonnegative_count(course.get("jehanInwon"))

    if registered_count is not None and registered_count > 0:
        return "registered"
    if courses is not None:
        haksu_no = course.get("haksuNo")
        suup_no = str(course.get("suupNo"))
        for sibling in courses:
            if sibling.get("haksuNo") != haksu_no:
                continue
            if str(sibling.get("suupNo")) == suup_no:
                continue
            sibling_count = _parse_nonnegative_count(
                sibling.get("sincheongSuupCnt")
            )
            if sibling_count is not None and sibling_count > 0:
                return "blocked"
    if registered_count is None:
        return "unknown"
    if enrolled_count is None or limit_count is None or limit_count == 0:
        return "unknown"
    if enrolled_count < limit_count:
        return "available"
    return "full"


def register_course(session, tokens, course_info, nf_key):
    """수강신청을 요청한다."""
    url = f"{BASE_URL}/SgscAct/hyuHaksaengSgsc.do?pgmId={tokens['pgmId']}&menuId={tokens['menuId']}&tk={tokens['tk']}"

    data = {
        "IN_JOJIK_GB_CD": str(course_info.get("jojikGbCd", "")),
        "IN_SINCHEONG_FLAG": "1",
        "IN_SUUP_NO": str(course_info.get("suupNo", "")),
        "IN_SUNSU_FLAG": "",
        "IN_JAESUGANG_YN": "N",
        "IN_A_JAESUGANG_GB": str(course_info.get("jaesugangGb", "")),
        "IN_JAESUGANG_HAKSU_NO": str(course_info.get("jaesugangHaksuNo", "") or ""),
        "IN_SGSC_GB": str(course_info.get("sgscGb", "0")),
        "IN_NETFUNNEL_KEY": nf_key,
        "IN_SEGMENT_KEY": "hyuSgSincheong",
        "IN_JAESUGANG_YEAR": str(course_info.get("jaesugangSuupYear", "") or ""),
        "IN_JAESUGANG_TERM": str(course_info.get("jaesugangSuupTerm", "") or ""),
        "IN_JAESUGANG_SUUP_NO": str(course_info.get("jaesugangSuupNo", "") or ""),
        "strReturnPopupYn": "N",
    }

    resp = session.post(url, json=data, headers=AJAX_HEADERS)
    result = resp.json()
    if not isinstance(result, dict):
        raise requests.RequestException("invalid registration response")

    out_code = result.get("outCode", "")
    out_msg = result.get("outMsg", "")

    return out_code, out_msg, result


def wait_until(target_time_str):
    """지정된 시간까지 대기한다."""
    target = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    diff = (target - now).total_seconds()

    if diff <= 0:
        log("지정된 시간이 이미 지났습니다. 즉시 실행합니다.", "yellow")
        return

    log(f"수강신청 시작 시간: {target_time_str}", "cyan")
    log(f"대기 중... ({diff:.0f}초 남음)", "cyan")

    # 10초 이상 남았으면 10초마다 출력
    while True:
        now = datetime.now()
        diff = (target - now).total_seconds()
        if diff <= 5:
            break
        if diff > 30:
            time.sleep(10)
            log(f"대기 중... ({diff:.0f}초 남음)", "cyan")
        else:
            time.sleep(1)
            log(f"대기 중... ({diff:.0f}초 남음)", "yellow")

    # 마지막 5초는 정밀 대기
    while datetime.now() < target:
        time.sleep(0.01)

    log("시간 도달! 수강신청을 시작합니다.", "green")


def prompt_credentials(questionary_module=None):
    if questionary_module is None:
        import questionary as questionary_module

    user_id = questionary_module.text("포털 ID").ask()
    if user_id is None:
        return None

    password = questionary_module.password("포털 비밀번호").ask()
    if password is None:
        return None

    return {
        "login_mode": "sso",
        "user_id": user_id.strip(),
        "password": password,
    }


def load_authentication(
    obtain_credentials_fn=obtain_validated_credentials,
    create_session_fn=create_session,
    store=None,
    questionary_module=None,
    legacy_path="secrets.json",
):
    if store is None:
        store = CredentialStore(default_credential_paths())

    def validator(credentials):
        candidate = {
            "login_mode": "sso",
            "user_id": credentials["user_id"],
            "password": credentials["password"],
        }
        try:
            return create_session_fn(candidate)
        except AuthenticationError:
            return None

    result = obtain_credentials_fn(
        store=store,
        prompt_credentials=lambda: prompt_credentials(questionary_module),
        validate_credentials=validator,
        legacy_path=legacy_path,
        on_storage_error=lambda error: log(
            f"저장된 인증 정보를 읽을 수 없습니다. 새 인증 정보를 입력합니다: {error}",
            "yellow",
        ),
    )
    if result.migrated_legacy:
        log(
            "secrets.json 인증 정보를 안전 저장소로 이전했습니다. "
            "기존 파일 삭제를 권장합니다: secrets.json",
            "yellow",
        )

    credentials = {
        "login_mode": "sso",
        "user_id": result.credentials["user_id"],
        "password": result.credentials["password"],
    }
    return credentials, result.validation


def select_run_mode(questionary_module=None):
    if questionary_module is None:
        import questionary as questionary_module

    choices = [
        questionary_module.Choice(
            "예약 수강신청 — 지정 시각 1회 시도 후 실패 과목 취케팅",
            value="scheduled",
        ),
        questionary_module.Choice(
            "바로 취케팅 — 정원 조회 후 빈자리 과목 신청",
            value="ticketing",
        ),
    ]
    return questionary_module.select(
        "실행 모드를 선택하세요",
        choices=choices,
        default="scheduled",
    ).ask()


def render_datetime_picker(state):
    values = (
        f"{state.value.year:04d}",
        f"{state.value.month:02d}",
        f"{state.value.day:02d}",
        f"{state.value.hour:02d}",
        f"{state.value.minute:02d}",
        f"{state.value.second:02d}",
    )
    separators = ("-", "-", "  ", ":", ":")
    fragments = [("class:label", "예약 시각: ")]
    for index, value in enumerate(values):
        style = "class:selected" if index == state.selected_index else "class:value"
        fragments.append((style, f"[{value}]"))
        if index < len(separators):
            fragments.append(("", separators[index]))
    fragments.extend(
        [
            ("", "\n"),
            ("class:help", "←/→ 항목 이동   ↑/↓ 값 변경   Enter 확정   Esc 취소"),
            ("", "\n"),
            ("class:error", state.error or ""),
        ]
    )
    return fragments


def run_datetime_picker(state, now_fn, input_stream=None, output=None):
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style

    bindings = KeyBindings()

    @bindings.add("left")
    def move_left(event):
        state.move(-1)
        event.app.invalidate()

    @bindings.add("right")
    def move_right(event):
        state.move(1)
        event.app.invalidate()

    @bindings.add("up")
    def increase(event):
        state.adjust(1)
        event.app.invalidate()

    @bindings.add("down")
    def decrease(event):
        state.adjust(-1)
        event.app.invalidate()

    @bindings.add("enter")
    def accept(event):
        target = state.confirm(now_fn())
        if target is None:
            event.app.invalidate()
        else:
            event.app.exit(result=target)

    @bindings.add("escape")
    @bindings.add("c-c")
    def cancel(event):
        event.app.exit(result=None)

    control = FormattedTextControl(
        text=lambda: render_datetime_picker(state),
        focusable=True,
        show_cursor=False,
    )
    application = Application(
        layout=Layout(Window(control, height=Dimension.exact(3))),
        key_bindings=bindings,
        style=Style.from_dict(
            {
                "label": "bold",
                "selected": "reverse bold ansicyan",
                "value": "ansicyan",
                "help": "ansibrightblack",
                "error": "ansired bold",
            }
        ),
        full_screen=False,
        erase_when_done=True,
        input=input_stream,
        output=output,
    )
    return application.run()


def prompt_target_time(now=None, now_fn=None, questionary_module=None, picker_fn=None):
    if now_fn is None:
        now_fn = datetime.now if now is None else lambda: now

    if picker_fn is not None:
        return picker_fn(DateTimePickerState.for_now(now_fn()), now_fn)
    if questionary_module is None and sys.stdin.isatty() and sys.stdout.isatty():
        return run_datetime_picker(DateTimePickerState.for_now(now_fn()), now_fn)
    if questionary_module is None:
        import questionary as questionary_module

    while True:
        answer = questionary_module.text(
            "예약 시간을 입력하세요 (YYYY-MM-DD HH:MM:SS)"
        ).ask()
        if answer is None:
            return None

        try:
            return parse_target_time(answer, now_fn())
        except ScheduleValidationError as error:
            log(str(error), "yellow")


def render_countdown_status(remaining, output=None):
    if output is None:
        output = sys.stdout
    output.write(f"\r\033[2K남은 시간: {remaining}")
    output.flush()


def clear_countdown_status(output=None):
    if output is None:
        output = sys.stdout
    output.write("\r\033[2K")
    output.flush()


def run_countdown(target, output=None):
    log(f"예약 수강신청 시각: {target.strftime('%Y-%m-%d %H:%M:%S')}", "cyan")
    try:
        countdown_until(
            target,
            now_fn=datetime.now,
            sleep_fn=time.sleep,
            render_fn=lambda remaining: render_countdown_status(remaining, output),
        )
    except KeyboardInterrupt:
        clear_countdown_status(output)
        log("예약 대기가 취소되었습니다.", "yellow")
        return False
    clear_countdown_status(output)
    log("시간 도달! 수강신청을 시작합니다.", "green")
    return True


def rematch_selected_courses(selected, refreshed):
    refreshed_by_suup = {
        str(course.get("suupNo")): course
        for course in refreshed
    }
    matched = []
    unresolved = []

    for course in selected:
        fresh_course = refreshed_by_suup.get(str(course.get("suupNo")))
        if fresh_course is None:
            unresolved.append(course)
        else:
            matched.append(fresh_course)

    return matched, unresolved


def refresh_registration_context(
    credentials,
    attempts=3,
    interval=0.5,
    create_session_fn=create_session,
    extract_tokens_fn=extract_tokens,
    fetch_course_list_fn=fetch_course_list,
):
    last_error = None
    for attempt in range(attempts):
        try:
            session = create_session_fn(credentials)
            tokens = extract_tokens_fn(session)
            courses = fetch_course_list_fn(session, tokens)
            return session, tokens, courses
        except AuthenticationError as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(interval)

    raise last_error or AuthenticationError("authentication failed")


def attempt_registration_course(
    session,
    tokens,
    course,
    attempt,
    get_key_fn=None,
    register_fn=None,
    release_key_fn=None,
):
    if get_key_fn is None:
        get_key_fn = get_netfunnel_key
    if register_fn is None:
        register_fn = register_course
    if release_key_fn is None:
        release_key_fn = release_netfunnel_key

    haksu_no = course.get("haksuNo", "?")
    gwamok_nm = course.get("gwamokNm", "?")
    log(f"[{attempt}] 신청 시도: {haksu_no} - {gwamok_nm}", "cyan")

    nf_key = get_key_fn(session)
    if not nf_key:
        log(f"[{attempt}] NetFunnel 키 발급 실패", "yellow")
        return "retry"

    try:
        out_code, out_msg, _ = register_fn(session, tokens, course, nf_key)
    except requests.RequestException as error:
        log(
            f"[{attempt}] 요청 오류: {haksu_no} - {error}. 다음 라운드에서 재시도합니다.",
            "yellow",
        )
        return "retry"
    finally:
        release_key_fn(session, nf_key)

    log(f"[{attempt}] 응답: [{out_code}] {out_msg}")
    status = classify_registration_result(out_code, out_msg)
    if status == "success":
        log(f"수강신청 성공: {haksu_no} - {gwamok_nm}", "green")
    elif status == "blocked":
        log(f"중복 과목으로 신청 중단: {haksu_no} - {gwamok_nm}", "yellow")
    else:
        log(f"수강신청 실패, 재시도 대기: {haksu_no} - {gwamok_nm}", "yellow")
    return status


def print_registration_summary(label, summary):
    log(
        f"{label} 완료 {len(summary.completed)}개, "
        f"대기 {len(summary.pending)}개, 중단 {len(summary.blocked)}개",
        "cyan",
    )
    for course in summary.blocked:
        log(
            f"중복 과목으로 중단: {course.get('haksuNo', '?')} - "
            f"{course.get('gwamokNm', '?')} (수업번호 {course.get('suupNo', '?')})",
            "yellow",
        )
    if summary.interrupted:
        log(f"{label} 중단됨", "yellow")


def run_application(
    load_authentication,
    fetch_context,
    select_courses,
    select_mode,
    select_target_time,
    run_countdown,
    refresh_context,
    attempt_course,
    wait_for_round,
    refresh_wishlist=None,
    ticketing_renderer=None,
):
    try:
        credentials, session = load_authentication()
    except (AuthenticationError, CredentialSetupCancelled) as error:
        log(f"인증을 완료하지 못했습니다: {error}", "red")
        return 1

    try:
        tokens, wishlist = fetch_context(session)
    except AuthenticationError as error:
        log(f"수강신청 토큰을 불러오지 못했습니다: {error}", "red")
        return 1
    if not wishlist:
        log("희망수업이 없습니다. 포털에서 희망수업을 먼저 등록해주세요.", "red")
        return 1

    selected = select_courses(wishlist)
    if not selected:
        log("선택된 과목이 없습니다. 실행을 종료합니다.", "yellow")
        return 1

    mode = select_mode()
    if mode is None:
        log("실행 모드 선택이 취소되었습니다.", "yellow")
        return 1
    if mode not in ("scheduled", "ticketing"):
        log("알 수 없는 실행 모드입니다.", "red")
        return 1

    def run_ticketing_for_context(courses, active_session, active_tokens, attempt):
        if refresh_wishlist is None:
            return run_ticketing(
                courses,
                attempt_course=attempt,
                wait_for_next_round=wait_for_round,
            )

        def poll_courses():
            try:
                return refresh_wishlist(active_session, active_tokens)
            except requests.RequestException as error:
                log(f"정원 조회 오류: {error}. 다음 조회에서 재시도합니다.", "yellow")
                return []

        return run_polling_ticketing(
            courses,
            poll_courses=poll_courses,
            classify_course=classify_ticketing_course,
            attempt_course=attempt,
            wait_for_next_poll=wait_for_round,
            on_poll=ticketing_renderer,
        )

    def finish_ticketing_line():
        if ticketing_renderer is not None:
            ticketing_renderer.finish()

    if mode == "ticketing":
        def attempt_with_initial_context(course, attempt_number):
            finish_ticketing_line()
            return attempt_course(session, tokens, course, attempt_number)

        summary = run_ticketing_for_context(
            selected,
            session,
            tokens,
            attempt_with_initial_context,
        )
        finish_ticketing_line()
        print_registration_summary("취케팅", summary)
        return 1 if summary.interrupted or summary.blocked else 0

    target = select_target_time()
    if target is None:
        log("예약 시간 입력이 취소되었습니다.", "yellow")
        return 1

    if run_countdown(target) is False:
        return 1
    try:
        fresh_session, fresh_tokens, refreshed = refresh_context(credentials)
    except AuthenticationError as error:
        log(f"예약 직전 재인증 실패: {error}", "red")
        return 1

    scheduled_courses, unresolved = rematch_selected_courses(selected, refreshed)
    for course in unresolved:
        log(
            f"새 희망수업 목록에서 찾을 수 없음: 수업번호 {course.get('suupNo', '?')}",
            "yellow",
        )
    if not scheduled_courses:
        log("새 희망수업 목록에서 신청할 과목을 찾지 못했습니다.", "red")
        return 1

    def attempt_with_fresh_context(course, attempt_number):
        finish_ticketing_line()
        return attempt_course(fresh_session, fresh_tokens, course, attempt_number)

    scheduled_summary = run_scheduled_pass(scheduled_courses, attempt_with_fresh_context)
    print_registration_summary("예약 수강신청", scheduled_summary)
    if scheduled_summary.interrupted:
        return 1

    if scheduled_summary.pending:
        ticketing_summary = run_ticketing_for_context(
            scheduled_summary.pending,
            fresh_session,
            fresh_tokens,
            attempt_with_fresh_context,
        )
        finish_ticketing_line()
        print_registration_summary("취케팅", ticketing_summary)
        if (
            scheduled_summary.blocked
            or ticketing_summary.interrupted
            or ticketing_summary.blocked
        ):
            return 1
        if unresolved:
            log(f"새 희망수업 목록에서 찾지 못한 과목 {len(unresolved)}개가 남았습니다.", "yellow")
            return 1
        return 0

    if unresolved:
        log(f"새 희망수업 목록에서 찾지 못한 과목 {len(unresolved)}개가 남았습니다.", "yellow")
        return 1

    return 1 if scheduled_summary.blocked else 0


def main():
    log("=== 한양대학교 수강신청 자동화 ===", "cyan")
    ticketing_renderer = TicketingPollRenderer()

    def fetch_initial_context(session):
        tokens = extract_tokens(session)
        courses = fetch_course_list(session, tokens)
        return tokens, courses

    def attempt(session, tokens, course, attempt_number):
        return attempt_registration_course(
            session,
            tokens,
            course,
            attempt_number,
        )

    exit_code = run_application(
        load_authentication=load_authentication,
        fetch_context=fetch_initial_context,
        select_courses=select_target_courses,
        select_mode=select_run_mode,
        select_target_time=prompt_target_time,
        run_countdown=run_countdown,
        refresh_context=refresh_registration_context,
        attempt_course=attempt,
        wait_for_round=lambda: time.sleep(0.5),
        refresh_wishlist=lambda session, tokens: fetch_course_list(
            session,
            tokens,
            log_result=False,
        ),
        ticketing_renderer=ticketing_renderer,
    )
    ticketing_renderer.finish()
    log(f"\n{'='*50}", "cyan")
    log("수강신청 자동화 완료", "cyan")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
