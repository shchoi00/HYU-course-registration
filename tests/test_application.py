from datetime import datetime, timedelta
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import (
    AuthenticationError,
    prompt_target_time,
    refresh_registration_context,
    rematch_selected_courses,
    run_application,
    select_run_mode,
)


class FakePrompt:
    def __init__(self, answer):
        self.answer = answer

    def ask(self):
        return self.answer


class FakeQuestionary:
    class Choice:
        def __init__(self, title, value):
            self.title = title
            self.value = value

    def __init__(self, select_answers=None, text_answers=None):
        self.select_answers = list(select_answers or [])
        self.text_answers = list(text_answers or [])
        self.select_calls = []
        self.text_calls = []

    def select(self, message, choices, default=None):
        self.select_calls.append(
            {"message": message, "choices": choices, "default": default}
        )
        return FakePrompt(self.select_answers.pop(0) if self.select_answers else None)

    def text(self, message):
        self.text_calls.append({"message": message})
        return FakePrompt(self.text_answers.pop(0) if self.text_answers else None)


class TestModeSelection(unittest.TestCase):
    def test_mode_menu_defaults_to_scheduled(self):
        prompts = FakeQuestionary(select_answers=["scheduled"])

        self.assertEqual(select_run_mode(prompts), "scheduled")
        self.assertEqual(prompts.select_calls[0]["default"], "scheduled")

    def test_cancelled_mode_prompt_sends_no_registration_requests(self):
        courses = [{"suupNo": "30012", "haksuNo": "COE8042", "gwamokNm": "확률과통계"}]
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, object()),
            fetch_context=lambda session: ({"tk": "token"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: None,
            select_target_time=lambda: self.fail("time prompt must not run"),
            run_countdown=lambda target: self.fail("countdown must not run"),
            refresh_context=lambda credentials: self.fail("refresh must not run"),
            attempt_course=lambda course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])


class TestScheduledApplication(unittest.TestCase):
    def test_scheduled_mode_refreshes_and_uses_new_course_payload(self):
        stale = {"suupNo": "30012", "marker": "stale"}
        fresh = {"suupNo": "30012", "marker": "fresh"}
        attempted = []
        target = datetime(2026, 8, 13, 10, 0, 0)

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "old"}, [stale]),
            select_courses=lambda wishlist: [stale],
            select_mode=lambda: "scheduled",
            select_target_time=lambda: target,
            run_countdown=lambda selected_target: None,
            refresh_context=lambda credentials: ("fresh-session", {"tk": "new"}, [fresh]),
            attempt_course=lambda course, attempt: attempted.append((course, attempt)) or "success",
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(attempted, [(fresh, 1)])

    def test_scheduled_failures_enter_ticketing_immediately(self):
        courses = [
            {"suupNo": "1", "name": "first"},
            {"suupNo": "2", "name": "second"},
            {"suupNo": "3", "name": "third"},
        ]
        outcomes = {"1": ["retry", "success"], "2": ["success"], "3": ["retry", "success"]}
        attempts = []
        waits = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "old"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
            run_countdown=lambda target: None,
            refresh_context=lambda credentials: ("fresh-session", {"tk": "new"}, courses),
            attempt_course=lambda course, attempt: attempts.append((course["suupNo"], attempt))
            or outcomes[course["suupNo"]].pop(0),
            wait_for_round=lambda: waits.append("wait"),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            attempts,
            [("1", 1), ("2", 1), ("3", 1), ("1", 1), ("3", 1)],
        )
        self.assertEqual(waits, [])

    def test_missing_selected_course_after_refresh_is_not_attempted(self):
        stale = {"suupNo": "30012", "marker": "stale"}
        fresh_other = {"suupNo": "99999", "marker": "fresh"}
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "old"}, [stale]),
            select_courses=lambda wishlist: [stale],
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
            run_countdown=lambda target: None,
            refresh_context=lambda credentials: ("fresh-session", {"tk": "new"}, [fresh_other]),
            attempt_course=lambda course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])


class TestRefreshContext(unittest.TestCase):
    def test_refresh_context_retries_authentication_three_times_then_raises(self):
        attempts = []

        def login(_credentials):
            attempts.append("login")
            raise AuthenticationError("invalid")

        with self.assertRaises(AuthenticationError):
            refresh_registration_context(
                {"user_id": "u", "password": "p"},
                attempts=3,
                interval=0,
                create_session_fn=login,
                extract_tokens_fn=lambda session: self.fail("tokens must not load"),
                fetch_course_list_fn=lambda session, tokens: self.fail("wishlist must not load"),
            )

        self.assertEqual(attempts, ["login", "login", "login"])

    def test_run_application_turns_refresh_authentication_failure_into_nonzero_exit(self):
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "old"}, [{"suupNo": "1"}]),
            select_courses=lambda wishlist: wishlist,
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
            run_countdown=lambda target: None,
            refresh_context=lambda credentials: (_ for _ in ()).throw(AuthenticationError("invalid")),
            attempt_course=lambda course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])


class TestPromptTargetTime(unittest.TestCase):
    def test_invalid_time_reprompts_without_defaulting_to_ticketing(self):
        now = datetime(2026, 8, 13, 9, 0, 0)
        prompts = FakeQuestionary(
            text_answers=[
                "2026/08/13 10:00",
                "2026-08-13 09:00:00",
                "2026-08-13 09:00:01",
            ]
        )

        target = prompt_target_time(now=now, questionary_module=prompts)

        self.assertEqual(target, now + timedelta(seconds=1))
        self.assertEqual(len(prompts.text_calls), 3)


class TestCourseRematch(unittest.TestCase):
    def test_rematches_strictly_by_stringified_suup_number(self):
        selected = [{"suupNo": 30012}, {"suupNo": "030012"}, {"suupNo": "30013"}]
        refreshed = [{"suupNo": "30012", "fresh": True}, {"suupNo": "30013", "fresh": True}]

        matched, unresolved = rematch_selected_courses(selected, refreshed)

        self.assertEqual(matched, [refreshed[0], refreshed[1]])
        self.assertEqual(unresolved, [selected[1]])


if __name__ == "__main__":
    unittest.main()
