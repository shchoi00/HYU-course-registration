#!/usr/bin/env python3
"""한양대학교 수강신청 자동화 시스템"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime

import requests

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
        log("config.json 파일이 없습니다. config.json.example을 참고하여 생성해주세요.", "red")
        sys.exit(1)

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    # secrets.json 로드 (선택 사항이지만 SSO 로그인 시 필수)
    if os.path.exists("secrets.json"):
        with open("secrets.json", "r", encoding="utf-8") as f:
            secrets = json.load(f)
            config.update(secrets)
    else:
        if config.get("login_mode") == "sso":
            log("SSO 로그인을 위해서는 secrets.json 파일이 필요합니다. secrets.json.example을 참고하여 생성해주세요.", "red")
            sys.exit(1)

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


def create_session(config):
    """로그인 모드에 따라 세션을 생성한다."""
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)

    if config["login_mode"] == "cookie":
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
    resp = session.get(f"{BASE_URL}/sulg.do")
    html = resp.text

    # tk 토큰 추출 (pgmId=P310298 관련)
    tk_match = re.search(r"pgmId=P310298&menuId=M008958&tk=([a-f0-9]+)", html)
    if not tk_match:
        # 다른 패턴 시도
        tk_match = re.search(r'tk=([a-f0-9]{64})', html)
    if not tk_match:
        log("tk 토큰을 찾을 수 없습니다.", "red")
        sys.exit(1)

    tk = tk_match.group(1)

    # 사용자 정보 추출
    gaein_match = re.search(r'gaeinNo\s*:\s*"(\d+)"', html)
    sosok_match = re.search(r'sosokCd\s*:\s*"([^"]+)"', html)
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


def fetch_course_list(session, tokens):
    """희망수업 목록을 조회한다."""
    url = f"{BASE_URL}/SgscAct/findHeemangSuupSearchs.do?pgmId={tokens['pgmId']}&menuId={tokens['menuId']}&tk={tokens['tk']}"
    data = {"strJojikGb": "2", "strGrade": "3"}

    resp = session.post(url, json=data, headers=AJAX_HEADERS)
    result = resp.json()

    courses = []
    ds = result.get("DS_SUUPGG03TTM01", [{}])
    if ds and "list" in ds[0]:
        courses = ds[0]["list"]

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
    if "이미" in out_msg and "신청" in out_msg:
        return "success"
    if out_code in ("", "SUCCESS", "S") or "성공" in out_msg or "완료" in out_msg:
        return "success"
    return "retry"


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


def main():
    config = load_config()
    log("=== 한양대학교 수강신청 자동화 ===", "cyan")

    # 1. 로그인
    try:
        session = create_session(config)
    except AuthenticationError:
        sys.exit(1)

    # 2. 토큰 추출
    tokens = extract_tokens(session)

    # 3. 희망수업 조회
    courses = fetch_course_list(session, tokens)

    if not courses:
        log("희망수업이 없습니다. 포털에서 희망수업을 먼저 등록해주세요.", "red")
        sys.exit(1)

    # 4. 신청 대상 및 우선순위 선택
    target_courses = select_target_courses(courses)

    if not target_courses:
        log("선택된 과목이 없습니다. 실행을 종료합니다.", "yellow")
        sys.exit(1)

    log("신청 우선순위", "cyan")
    for priority, course in enumerate(target_courses, start=1):
        log(
            f"  {priority}순위: {course.get('gwamokNm', '?')} "
            f"({course.get('haksuNo', '?')}, 수업번호 {course.get('suupNo', '?')})",
            "cyan",
        )

    # 5. 예약 시간까지 대기
    if config.get("schedule", {}).get("enabled"):
        wait_until(config["schedule"]["start_time"])

    # 6. 우선순위 라운드 로빈 수강신청
    max_attempts = config.get("retry", {}).get("max_attempts", 50)
    interval = config.get("retry", {}).get("interval_seconds", 0.5)

    def attempt_course(course, attempt):
        haksu_no = course.get("haksuNo", "?")
        gwamok_nm = course.get("gwamokNm", "?")
        log(f"[{attempt}/{max_attempts}] 신청 시도: {haksu_no} - {gwamok_nm}", "cyan")

        nf_key = get_netfunnel_key(session)
        if not nf_key:
            log(f"[{attempt}/{max_attempts}] NetFunnel 키 발급 실패", "yellow")
            return "retry"

        try:
            out_code, out_msg, _ = register_course(
                session,
                tokens,
                course,
                nf_key,
            )
        finally:
            release_netfunnel_key(session, nf_key)

        log(f"[{attempt}/{max_attempts}] 응답: [{out_code}] {out_msg}")
        status = classify_registration_result(out_code, out_msg)

        if status == "success":
            if "이미" in out_msg and "신청" in out_msg:
                log(f"이미 신청된 과목입니다: {haksu_no}", "yellow")
            else:
                log(f"수강신청 성공! {haksu_no} - {gwamok_nm}", "green")
        elif out_code == "M77":
            log("수강신청 기간이 아닙니다. 다음 라운드에서 재시도합니다.", "yellow")

        return status

    def log_attempt_error(course, attempt, error):
        log(
            f"[{attempt}/{max_attempts}] 요청 오류: "
            f"{course.get('haksuNo', '?')} - {error}. 다음 라운드에서 재시도합니다.",
            "yellow",
        )

    results = run_registration_round_robin(
        target_courses,
        max_attempts=max_attempts,
        attempt_course=attempt_course,
        wait_for_next_round=lambda: time.sleep(interval),
        on_attempt_error=log_attempt_error,
    )

    for result in results:
        if result["status"] != "failed":
            continue
        course = result["course"]
        log(
            f"수강신청 실패: {course.get('haksuNo', '?')} - "
            f"{course.get('gwamokNm', '?')} ({result['attempts']}회 시도)",
            "red",
        )

    log(f"\n{'='*50}", "cyan")
    log("수강신청 자동화 완료", "cyan")


if __name__ == "__main__":
    main()
