import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import questionary
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from credentials import CredentialPaths, CredentialStore
from main import (
    AuthenticationError,
    attempt_registration_course,
    classify_registration_result,
    extract_tokens,
    load_authentication,
    order_courses_by_priority,
    register_course,
    run_application,
    select_target_courses,
)
from workflow import run_ticketing


class TestCoursePriority(unittest.TestCase):
    def setUp(self):
        self.courses = [
            {
                "haksuNo": "CSE1001",
                "suupNo": "10001",
                "gwamokNm": "첫 번째 과목",
                "jojikGbCd": "H0001",
                "sgscGb": "0",
            },
            {
                "haksuNo": "CSE1002",
                "suupNo": "10002",
                "gwamokNm": "두 번째 과목",
                "jojikGbCd": "H0001",
                "sgscGb": "0",
            },
            {
                "haksuNo": "CSE1003",
                "suupNo": "10003",
                "gwamokNm": "세 번째 과목",
                "jojikGbCd": "H0001",
                "sgscGb": "0",
            },
        ]

    def test_orders_selected_courses_by_each_priority_choice(self):
        requested_priorities = []

        def choose(priority, remaining):
            requested_priorities.append(
                (priority, [course["suupNo"] for course in remaining])
            )
            return remaining[-1] if priority == 1 else remaining[0]

        ordered = order_courses_by_priority(self.courses, choose)

        self.assertEqual(
            [course["suupNo"] for course in ordered],
            ["10003", "10001", "10002"],
        )
        self.assertEqual(
            requested_priorities,
            [(1, ["10001", "10002", "10003"]), (2, ["10001", "10002"])],
        )


class TestCourseListFetch(unittest.TestCase):
    def test_polling_fetch_returns_courses_without_writing_repeated_logs(self):
        course = {
            "haksuNo": "COE9016",
            "suupNo": "30023",
            "gwamokNm": "SF영화와철학적사고실험",
            "sincheongSuupCnt": 0,
            "sincheongInwon": "180",
            "jehanInwon": "180",
        }

        class Response:
            @staticmethod
            def json():
                return {"DS_SUUPGG03TTM01": [{"list": [course]}]}

        class Session:
            @staticmethod
            def post(_url, json, headers):
                return Response()

        logs = []
        with patch("main.log", side_effect=lambda *args: logs.append(args)):
            courses = main.fetch_course_list(
                Session(),
                {"pgmId": "p", "menuId": "m", "tk": "t"},
                log_result=False,
            )

        self.assertEqual(courses, [course])
        self.assertEqual(logs, [])

    def test_non_object_wishlist_response_is_a_retryable_request_error(self):
        class Response:
            @staticmethod
            def json():
                return []

        class Session:
            @staticmethod
            def post(_url, json, headers):
                return Response()

        with self.assertRaises(requests.RequestException):
            main.fetch_course_list(
                Session(),
                {"pgmId": "p", "menuId": "m", "tk": "t"},
                log_result=False,
            )


class TestTokenExtraction(unittest.TestCase):
    def test_extracts_url_safe_token_with_html_entities_and_mixed_case(self):
        class Response:
            text = (
                'url: "openPage.do?pgmId=P320035&amp;tk=AbC_123-XyZ.9876543210"; '
                'gaeinNo: "2026123456"; sosokCd: "H0001"'
            )

        class Session:
            @staticmethod
            def get(_url):
                return Response()

        tokens = extract_tokens(Session())

        self.assertEqual(tokens["tk"], "AbC_123-XyZ.9876543210")
        self.assertEqual(tokens["gaeinNo"], "2026123456")
        self.assertEqual(tokens["sosokCd"], "H0001")

    def test_retries_token_extraction_through_login_landing_page(self):
        class Response:
            def __init__(self, text):
                self.text = text

        class Session:
            def __init__(self):
                self.urls = []

            def get(self, url):
                self.urls.append(url)
                if url.endswith("/sulg.do"):
                    return Response("<html><body>메뉴 준비 중</body></html>")
                return Response(
                    'url: "openPage.do?pgmId=P320035&tk=retry_TOKEN-1234567890"'
                )

        session = Session()
        tokens = extract_tokens(session)

        self.assertEqual(tokens["tk"], "retry_TOKEN-1234567890")
        self.assertEqual(
            session.urls,
            [
                f"{main.BASE_URL}/sulg.do",
                f"{main.BASE_URL}/slgns.do?locale=ko",
            ],
        )

    def test_missing_token_raises_authentication_error_instead_of_exiting_process(self):
        class Response:
            text = "<html><body>수강신청 메인</body></html>"

        class Session:
            @staticmethod
            def get(_url):
                return Response()

        with self.assertRaisesRegex(AuthenticationError, "token"):
            extract_tokens(Session())


class TestTicketingRegistration(unittest.TestCase):
    def test_non_object_registration_response_is_a_retryable_request_error(self):
        class Response:
            @staticmethod
            def json():
                return []

        class Session:
            @staticmethod
            def post(_url, json, headers):
                return Response()

        with self.assertRaises(requests.RequestException):
            register_course(
                Session(),
                {"pgmId": "p", "menuId": "m", "tk": "t"},
                {"suupNo": "30023"},
                "nf-key",
            )

    def test_duplicate_course_attempt_logs_terminal_block_instead_of_retry(self):
        course = {
            "haksuNo": "COE8042",
            "suupNo": "30012",
            "gwamokNm": "확률과통계",
        }
        logs = []

        with patch("main.log", side_effect=lambda message, color=None: logs.append(message)):
            status = attempt_registration_course(
                object(),
                {"tk": "token"},
                course,
                1,
                get_key_fn=lambda session: "nf-key",
                register_fn=lambda session, tokens, selected, key: (
                    "MSG",
                    "수업과목을 중복 신청하였습니다. 수강신청 내역을 확인하여 주십시오",
                    {},
                ),
                release_key_fn=lambda session, key: None,
            )

        self.assertEqual(status, "blocked")
        self.assertTrue(any("중복 과목" in message and "중단" in message for message in logs))
        self.assertFalse(any("재시도 대기" in message for message in logs))

    def test_transient_request_error_does_not_skip_later_courses(self):
        courses = [
            {"haksuNo": "CSE1001", "suupNo": "10001", "gwamokNm": "1순위"},
            {"haksuNo": "CSE1002", "suupNo": "10002", "gwamokNm": "2순위"},
        ]
        calls = []

        def attempt(course, attempt_number):
            suup_no = course["suupNo"]
            calls.append((suup_no, attempt_number))
            if suup_no == "10001" and attempt_number == 1:
                try:
                    raise requests.RequestException("temporary network failure")
                except requests.RequestException:
                    return "retry"
            return "success"

        summary = run_ticketing(
            courses,
            attempt_course=attempt,
        )

        self.assertEqual(
            calls,
            [("10001", 1), ("10002", 1), ("10001", 2)],
        )
        self.assertEqual(
            [course["suupNo"] for course in summary.completed],
            ["10001", "10002"],
        )
        self.assertEqual(summary.pending, [])

    def test_retries_remaining_courses_once_per_priority_round(self):
        courses = [
            {"haksuNo": "CSE1001", "suupNo": "10001", "gwamokNm": "1순위"},
            {"haksuNo": "CSE1002", "suupNo": "10002", "gwamokNm": "2순위"},
            {"haksuNo": "CSE1003", "suupNo": "10003", "gwamokNm": "3순위"},
        ]
        outcomes = {
            "10001": ["retry", "success"],
            "10002": ["success"],
            "10003": ["retry", "retry", "success"],
        }
        calls = []
        waits = []

        def attempt(course, attempt_number):
            suup_no = course["suupNo"]
            calls.append((suup_no, attempt_number))
            return outcomes[suup_no].pop(0)

        summary = run_ticketing(
            courses,
            attempt_course=attempt,
            wait_for_next_round=lambda: waits.append("wait"),
        )

        self.assertEqual(
            calls,
            [
                ("10001", 1),
                ("10002", 1),
                ("10003", 1),
                ("10001", 2),
                ("10003", 2),
                ("10003", 3),
            ],
        )
        self.assertEqual(waits, ["wait", "wait"])
        self.assertEqual(
            [course["suupNo"] for course in summary.completed],
            ["10001", "10002", "10003"],
        )
        self.assertEqual(summary.pending, [])

    def test_registration_attempt_request_error_releases_key_and_allows_next_course(self):
        courses = [
            {"haksuNo": "CSE1001", "suupNo": "10001", "gwamokNm": "1순위"},
            {"haksuNo": "CSE1002", "suupNo": "10002", "gwamokNm": "2순위"},
        ]
        session = object()
        tokens = {"tk": "token"}
        released = []
        failures = {"10001": 1}

        def register(_session, _tokens, course, _key):
            if failures.get(course["suupNo"], 0):
                failures[course["suupNo"]] -= 1
                raise requests.RequestException("temporary")
            return "S", "신청 완료", {}

        with patch("main.get_netfunnel_key", return_value="nf-key"), \
                patch("main.register_course", side_effect=register), \
                patch("main.release_netfunnel_key", side_effect=lambda _session, key: released.append(key)):
            summary = run_ticketing(
                courses,
                attempt_course=lambda course, attempt: attempt_registration_course(
                    session,
                    tokens,
                    course,
                    attempt,
                ),
            )

        self.assertEqual([course["suupNo"] for course in summary.completed], ["10001", "10002"])
        self.assertEqual(summary.pending, [])
        self.assertEqual(released, ["nf-key", "nf-key", "nf-key"])

    def test_invalid_prompted_credentials_retry_and_only_valid_credentials_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )
            prompts = FakeCredentialQuestionary([
                ("wrong-user", "wrong-pass"),
                ("valid-user", "valid-pass"),
            ])
            attempts = []
            valid_session = object()

            def create_session(credentials):
                attempts.append(credentials)
                if credentials["user_id"] == "wrong-user":
                    raise AuthenticationError("invalid credentials")
                return valid_session

            credentials, session = load_authentication(
                create_session_fn=create_session,
                store=store,
                questionary_module=prompts,
                legacy_path=root / "missing-secrets.json",
            )

            self.assertEqual(credentials["user_id"], "valid-user")
            self.assertEqual(credentials["password"], "valid-pass")
            self.assertIs(session, valid_session)
            self.assertEqual(store.load(), {"user_id": "valid-user", "password": "valid-pass"})
            self.assertEqual(
                [(attempt["user_id"], attempt["password"]) for attempt in attempts],
                [("wrong-user", "wrong-pass"), ("valid-user", "valid-pass")],
            )

    def test_invalid_prompted_credentials_then_cancel_returns_nonzero_without_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )
            prompts = FakeCredentialQuestionary([
                ("wrong-user", "wrong-pass"),
                None,
            ])

            def load_auth():
                return load_authentication(
                    create_session_fn=lambda _credentials: (_ for _ in ()).throw(
                        AuthenticationError("invalid credentials")
                    ),
                    store=store,
                    questionary_module=prompts,
                    legacy_path=root / "missing-secrets.json",
                )

            exit_code = run_application(
                load_authentication=load_auth,
                fetch_context=lambda session: self.fail("fetch must not run after cancel"),
                select_courses=lambda wishlist: self.fail("selection must not run after cancel"),
                select_mode=lambda: self.fail("mode prompt must not run after cancel"),
                select_target_time=lambda: self.fail("time prompt must not run after cancel"),
                run_countdown=lambda target: self.fail("countdown must not run after cancel"),
                refresh_context=lambda credentials: self.fail("refresh must not run after cancel"),
                attempt_course=lambda course, attempt: self.fail("registration must not run after cancel"),
                wait_for_round=lambda: None,
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(prompts.credential_answers, [])
            self.assertFalse(store.paths.key_path.exists())
            self.assertFalse(store.paths.token_path.exists())


class TestRegistrationResultClassification(unittest.TestCase):
    def test_success_response_is_not_retried(self):
        self.assertEqual(classify_registration_result("S", "신청 완료"), "success")

    def test_already_registered_response_is_treated_as_success(self):
        self.assertEqual(
            classify_registration_result("E01", "이미 신청된 과목입니다."),
            "success",
        )

    def test_empty_response_is_retried_instead_of_reported_as_success(self):
        self.assertEqual(classify_registration_result("", ""), "retry")

    def test_duplicate_course_response_is_blocked_instead_of_retried(self):
        self.assertEqual(
            classify_registration_result(
                "MSG",
                "수업과목을 중복 신청하였습니다. 수강신청 내역을 확인하여 주십시오",
            ),
            "blocked",
        )

    def test_registration_period_response_is_retried(self):
        self.assertEqual(
            classify_registration_result("M77", "수강신청 기간이 아닙니다."),
            "retry",
        )

    def test_other_failure_is_retried(self):
        self.assertEqual(
            classify_registration_result("E99", "일시적인 오류입니다."),
            "retry",
        )


class TestTicketingCourseClassification(unittest.TestCase):
    def test_classifies_registration_and_capacity_from_wishlist_counts(self):
        cases = [
            (
                {"sincheongSuupCnt": 1, "sincheongInwon": "120", "jehanInwon": "120"},
                "registered",
            ),
            (
                {"sincheongSuupCnt": 0, "sincheongInwon": "180", "jehanInwon": "180"},
                "full",
            ),
            (
                {"sincheongSuupCnt": 0, "sincheongInwon": "179", "jehanInwon": "180"},
                "available",
            ),
            (
                {"sincheongSuupCnt": 0, "sincheongInwon": None, "jehanInwon": "180"},
                "unknown",
            ),
        ]

        for course, expected in cases:
            with self.subTest(course=course):
                self.assertEqual(main.classify_ticketing_course(course), expected)

    def test_blocks_selected_section_when_another_section_is_already_registered(self):
        selected = {
            "haksuNo": "COE8042",
            "suupNo": "30012",
            "sincheongSuupCnt": 0,
            "sincheongInwon": "120",
            "jehanInwon": "120",
        }
        registered_sibling = {
            "haksuNo": "COE8042",
            "suupNo": "30011",
            "sincheongSuupCnt": 1,
            "sincheongInwon": "120",
            "jehanInwon": "120",
        }

        self.assertEqual(
            main.classify_ticketing_course(
                selected,
                [selected, registered_sibling],
            ),
            "blocked",
        )

    def test_blocks_missing_selected_section_when_registered_sibling_remains(self):
        selected = {
            "haksuNo": "COE8042",
            "suupNo": "30012",
        }
        registered_sibling = {
            "haksuNo": "COE8042",
            "suupNo": "30011",
            "sincheongSuupCnt": 1,
            "sincheongInwon": "120",
            "jehanInwon": "120",
        }

        self.assertEqual(
            main.classify_ticketing_course(
                selected,
                [registered_sibling],
            ),
            "blocked",
        )


class FakePrompt:
    def __init__(self, answer):
        self.answer = answer

    def ask(self):
        return self.answer


class FakeCredentialQuestionary:
    def __init__(self, credential_answers):
        self.credential_answers = list(credential_answers)
        self.current = None

    def text(self, _message):
        self.current = self.credential_answers.pop(0)
        if self.current is None:
            return FakePrompt(None)
        return FakePrompt(self.current[0])

    def password(self, _message):
        return FakePrompt(self.current[1])


class FakeQuestionary:
    class Choice:
        def __init__(self, title, value):
            self.title = title
            self.value = value

    def __init__(self, selected, priorities):
        self.selected = selected
        self.priorities = list(priorities)
        self.checkbox_choices = []

    def checkbox(self, _message, choices):
        self.checkbox_choices = choices
        return FakePrompt(self.selected)

    def select(self, _message, choices):
        selected = self.priorities.pop(0)
        self.asserted_remaining = [choice.value for choice in choices]
        return FakePrompt(selected)


class TestInteractiveCourseSelection(unittest.TestCase):
    def test_installed_questionary_can_construct_checkbox_prompt(self):
        prompt = questionary.checkbox(
            "신청할 희망수업을 선택하세요",
            choices=["자료구조", "운영체제"],
        )

        self.assertIsNotNone(prompt)

    def test_selects_from_wishlist_and_returns_priority_order(self):
        courses = [
            {"haksuNo": "CSE1001", "suupNo": "10001", "gwamokNm": "자료구조"},
            {"haksuNo": "CSE1002", "suupNo": "10002", "gwamokNm": "운영체제"},
            {"haksuNo": "CSE1003", "suupNo": "10003", "gwamokNm": "컴퓨터구조"},
        ]
        prompts = FakeQuestionary(
            selected=[courses[0], courses[2]],
            priorities=[courses[2]],
        )

        selected = select_target_courses(courses, prompts)

        self.assertEqual(
            [course["suupNo"] for course in selected],
            ["10003", "10001"],
        )
        self.assertEqual(
            [choice.title for choice in prompts.checkbox_choices],
            [
                "자료구조 | CSE1001 | 수업번호 10001",
                "운영체제 | CSE1002 | 수업번호 10002",
                "컴퓨터구조 | CSE1003 | 수업번호 10003",
            ],
        )


if __name__ == "__main__":
    unittest.main()
