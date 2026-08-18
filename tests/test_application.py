import io
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
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
    def test_ticketing_poll_renderer_reuses_one_terminal_line(self):
        output = io.StringIO()
        renderer = main.TicketingPollRenderer(stream=output)
        course = {
            "haksuNo": "COE9016",
            "sincheongInwon": "180",
            "jehanInwon": "180",
        }

        renderer(1, [(course, "full")])
        renderer(
            2,
            [({**course, "sincheongInwon": "179"}, "available")],
        )
        renderer.finish()

        rendered = output.getvalue()
        self.assertIn("[취케팅 조회 1] COE9016 180/180 만석", rendered)
        self.assertIn("[취케팅 조회 2] COE9016 179/180 빈자리", rendered)
        self.assertEqual(rendered.count("\n"), 1)

    def test_mode_menu_defaults_to_scheduled(self):
        prompts = FakeQuestionary(select_answers=["scheduled"])

        self.assertEqual(select_run_mode(prompts), "scheduled")
        self.assertEqual(prompts.select_calls[0]["default"], "scheduled")
        self.assertIn(
            "정원 조회",
            prompts.select_calls[0]["choices"][1].title,
        )

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
            attempt_course=lambda session, tokens, course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])

    def test_missing_token_after_login_returns_nonzero_without_traceback(self):
        logs = []

        with patch("main.log", side_effect=lambda message, color=None: logs.append(message)):
            exit_code = run_application(
                load_authentication=lambda: (
                    {"user_id": "u", "password": "p"},
                    "session",
                ),
                fetch_context=lambda session: (_ for _ in ()).throw(
                    AuthenticationError("tk token not found")
                ),
                select_courses=lambda wishlist: self.fail("selection must not run"),
                select_mode=lambda: self.fail("mode prompt must not run"),
                select_target_time=lambda: self.fail("time prompt must not run"),
                run_countdown=lambda target: self.fail("countdown must not run"),
                refresh_context=lambda credentials: self.fail("refresh must not run"),
                attempt_course=lambda session, tokens, course, attempt: self.fail(
                    "registration must not run"
                ),
                wait_for_round=lambda: None,
            )

        self.assertEqual(exit_code, 1)
        self.assertTrue(any("토큰" in message for message in logs))

    def test_direct_ticketing_polls_wishlist_before_attempt_and_confirms_registration(self):
        selected = {
            "suupNo": "30023",
            "haksuNo": "COE9016",
            "sincheongSuupCnt": 0,
            "sincheongInwon": "180",
            "jehanInwon": "180",
        }
        snapshots = [
            [{**selected, "sincheongInwon": "180"}],
            [{**selected, "sincheongInwon": "179", "marker": "available"}],
            [{**selected, "sincheongSuupCnt": 1, "marker": "registered"}],
        ]
        refreshes = []
        attempts = []
        waits = []

        class Renderer:
            def __init__(self):
                self.polls = []
                self.finishes = 0

            def __call__(self, poll_number, observations):
                self.polls.append(
                    (poll_number, [status for _course, status in observations])
                )

            def finish(self):
                self.finishes += 1

        renderer = Renderer()

        def refresh_wishlist(session, tokens):
            refreshes.append((session, tokens))
            return snapshots.pop(0)

        exit_code = run_application(
            load_authentication=lambda: (
                {"user_id": "u", "password": "p"},
                "initial-session",
            ),
            fetch_context=lambda session: ({"tk": "initial-token"}, [selected]),
            select_courses=lambda wishlist: [selected],
            select_mode=lambda: "ticketing",
            select_target_time=lambda: self.fail("time prompt must not run"),
            run_countdown=lambda target: self.fail("countdown must not run"),
            refresh_context=lambda credentials: self.fail("refresh must not run"),
            attempt_course=lambda session, tokens, course, attempt: attempts.append(
                (session, tokens, course.get("marker"), attempt)
            )
            or "success",
            wait_for_round=lambda: waits.append("wait"),
            refresh_wishlist=refresh_wishlist,
            ticketing_renderer=renderer,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            refreshes,
            [
                ("initial-session", {"tk": "initial-token"}),
                ("initial-session", {"tk": "initial-token"}),
                ("initial-session", {"tk": "initial-token"}),
            ],
        )
        self.assertEqual(
            attempts,
            [("initial-session", {"tk": "initial-token"}, "available", 1)],
        )
        self.assertEqual(waits, ["wait", "wait"])
        self.assertEqual(
            renderer.polls,
            [(1, ["full"]), (2, ["available"]), (3, ["registered"])],
        )
        self.assertGreaterEqual(renderer.finishes, 2)

    def test_direct_ticketing_blocks_when_only_registered_sibling_remains(self):
        selected = {
            "suupNo": "30012",
            "haksuNo": "COE8042",
            "sincheongSuupCnt": 0,
            "sincheongInwon": "119",
            "jehanInwon": "120",
        }
        registered_sibling = {
            **selected,
            "suupNo": "30011",
            "sincheongSuupCnt": 1,
        }
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: (
                {"user_id": "u", "password": "p"},
                "initial-session",
            ),
            fetch_context=lambda session: ({"tk": "initial-token"}, [selected]),
            select_courses=lambda wishlist: [selected],
            select_mode=lambda: "ticketing",
            select_target_time=lambda: self.fail("time prompt must not run"),
            run_countdown=lambda target: self.fail("countdown must not run"),
            refresh_context=lambda credentials: self.fail("refresh must not run"),
            attempt_course=lambda session, tokens, course, attempt: attempts.append(
                (course, attempt)
            )
            or "success",
            wait_for_round=lambda: self.fail("blocked course must not wait"),
            refresh_wishlist=lambda session, tokens: [registered_sibling],
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])


class TestTicketingPollWait(unittest.TestCase):
    def test_ticketing_poll_wait_uses_uniform_point_seven_to_one_point_three(self):
        wait_fn = getattr(main, "wait_for_ticketing_poll", None)
        self.assertIsNotNone(wait_fn)
        requested_ranges = []
        sleeps = []

        wait_fn(
            sleep_fn=sleeps.append,
            uniform_fn=lambda minimum, maximum: requested_ranges.append(
                (minimum, maximum)
            )
            or 0.94,
        )

        self.assertEqual(requested_ranges, [(0.7, 1.3)])
        self.assertEqual(sleeps, [0.94])


class TestMainWiring(unittest.TestCase):
    def test_main_enables_quiet_wishlist_polling_and_terminal_renderer(self):
        captured = {}
        fetches = []

        def fake_run_application(**kwargs):
            captured.update(kwargs)
            return 0

        def fake_fetch(session, tokens, log_result=True):
            fetches.append((session, tokens, log_result))
            return [{"suupNo": "1"}]

        with patch("main.run_application", side_effect=fake_run_application), patch(
            "main.fetch_course_list", side_effect=fake_fetch
        ), patch("main.log"), patch("main.sys.exit"):
            main.main()
            polled = captured["refresh_wishlist"](
                "session",
                {"tk": "token"},
            )

        self.assertEqual(polled, [{"suupNo": "1"}])
        self.assertEqual(fetches, [("session", {"tk": "token"}, False)])
        self.assertIsInstance(captured["ticketing_renderer"], main.TicketingPollRenderer)
        self.assertIs(
            captured["wait_for_round"],
            getattr(main, "wait_for_ticketing_poll", None),
        )


class TestScheduledApplication(unittest.TestCase):
    def test_cancelled_countdown_stops_before_refresh_or_registration(self):
        courses = [{"suupNo": "30012"}]
        refreshes = []
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "session"),
            fetch_context=lambda session: ({"tk": "token"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 18, 9, 0, 0),
            run_countdown=lambda target: False,
            refresh_context=lambda credentials: refreshes.append(credentials),
            attempt_course=lambda session, tokens, course, attempt: attempts.append(course),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(refreshes, [])
        self.assertEqual(attempts, [])

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
            attempt_course=lambda session, tokens, course, attempt: attempted.append((course, attempt)) or "success",
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
            attempt_course=lambda session, tokens, course, attempt: attempts.append((course["suupNo"], attempt))
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
            attempt_course=lambda session, tokens, course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])

    def test_partial_refresh_rematch_attempts_only_fresh_courses_and_returns_nonzero(self):
        stale_missing = {"suupNo": "30012", "marker": "stale-missing"}
        stale_matched = {"suupNo": "30013", "marker": "stale-matched"}
        fresh_matched = {"suupNo": "30013", "marker": "fresh-matched"}
        attempts = []
        logs = []

        with patch("main.log", side_effect=lambda message, color=None: logs.append(message)):
            exit_code = run_application(
                load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
                fetch_context=lambda session: ({"tk": "old"}, [stale_missing, stale_matched]),
                select_courses=lambda wishlist: [stale_missing, stale_matched],
                select_mode=lambda: "scheduled",
                select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
                run_countdown=lambda target: None,
                refresh_context=lambda credentials: ("fresh-session", {"tk": "new"}, [fresh_matched]),
                attempt_course=lambda session, tokens, course, attempt: attempts.append((course, attempt)) or "success",
                wait_for_round=lambda: None,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [(fresh_matched, 1)])
        self.assertTrue(any("30012" in message for message in logs))

    def test_direct_ticketing_attempts_with_initial_auth_context(self):
        courses = [{"suupNo": "30012"}]
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "initial-token"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: "ticketing",
            select_target_time=lambda: self.fail("time prompt must not run"),
            run_countdown=lambda target: self.fail("countdown must not run"),
            refresh_context=lambda credentials: self.fail("refresh must not run"),
            attempt_course=lambda session, tokens, course, attempt: attempts.append(
                (session, tokens, course, attempt)
            ) or "success",
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(attempts, [("initial-session", {"tk": "initial-token"}, courses[0], 1)])

    def test_scheduled_and_ticketing_handoff_attempt_with_refreshed_auth_context(self):
        courses = [{"suupNo": "1"}, {"suupNo": "2"}]
        outcomes = {"1": ["retry", "success"], "2": ["success"]}
        attempts = []

        exit_code = run_application(
            load_authentication=lambda: ({"user_id": "u", "password": "p"}, "initial-session"),
            fetch_context=lambda session: ({"tk": "initial-token"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
            run_countdown=lambda target: None,
            refresh_context=lambda credentials: ("fresh-session", {"tk": "fresh-token"}, courses),
            attempt_course=lambda session, tokens, course, attempt: attempts.append(
                (session, tokens, course["suupNo"], attempt)
            ) or outcomes[course["suupNo"]].pop(0),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            attempts,
            [
                ("fresh-session", {"tk": "fresh-token"}, "1", 1),
                ("fresh-session", {"tk": "fresh-token"}, "2", 1),
                ("fresh-session", {"tk": "fresh-token"}, "1", 1),
            ],
        )

    def test_scheduled_block_remains_nonzero_after_other_courses_finish_ticketing(self):
        blocked = {"haksuNo": "CSE1001", "suupNo": "1"}
        pending = {"haksuNo": "CSE1002", "suupNo": "2"}
        courses = [blocked, pending]
        attempts = []

        def attempt(_session, _tokens, course, attempt_number):
            attempts.append((course["suupNo"], attempt_number))
            return "blocked" if course["suupNo"] == "1" else "retry"

        exit_code = run_application(
            load_authentication=lambda: (
                {"user_id": "u", "password": "p"},
                "initial-session",
            ),
            fetch_context=lambda session: ({"tk": "initial-token"}, courses),
            select_courses=lambda wishlist: courses,
            select_mode=lambda: "scheduled",
            select_target_time=lambda: datetime(2026, 8, 13, 10, 0, 0),
            run_countdown=lambda target: None,
            refresh_context=lambda credentials: (
                "fresh-session",
                {"tk": "fresh-token"},
                courses,
            ),
            attempt_course=attempt,
            wait_for_round=lambda: None,
            refresh_wishlist=lambda session, tokens: [
                blocked,
                {**pending, "sincheongSuupCnt": "1"},
            ],
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [("1", 1), ("2", 1)])


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
            attempt_course=lambda session, tokens, course, attempt: attempts.append((course, attempt)),
            wait_for_round=lambda: None,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(attempts, [])


class TestPromptTargetTime(unittest.TestCase):
    def test_datetime_picker_applies_arrow_keys_and_accepts_with_enter(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        now = datetime(2026, 1, 1, 8, 0, 0)
        state = main.DateTimePickerState.for_now(now)

        with create_pipe_input() as pipe_input:
            pipe_input.send_text(
                "\x1b[A"  # day: 1 -> 2
                "\x1b[D"  # select month
                "\x1b[A"  # month: January -> February
                "\x1b[C"  # select day
                "\x1b[C"  # select hour
                "\x1b[A"  # hour: 09 -> 10
                "\x1b[C"  # select minute
                "\x1b[B"  # minute: 00 -> 59
                "\r"
            )
            target = main.run_datetime_picker(
                state,
                now_fn=lambda: now,
                input_stream=pipe_input,
                output=DummyOutput(),
            )

        self.assertEqual(target, datetime(2026, 2, 2, 10, 59, 0))

    def test_datetime_picker_cancels_with_escape_or_control_c(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        now = datetime(2026, 1, 1, 8, 0, 0)

        for key in ("\x1b", "\x03"):
            with self.subTest(key=repr(key)), create_pipe_input() as pipe_input:
                pipe_input.send_text(key)
                target = main.run_datetime_picker(
                    main.DateTimePickerState.for_now(now),
                    now_fn=lambda: now,
                    input_stream=pipe_input,
                    output=DummyOutput(),
                )

                self.assertIsNone(target)

    def test_interactive_picker_starts_today_at_nine(self):
        now = datetime(2026, 8, 14, 23, 48, 54)
        selected = datetime(2026, 8, 18, 9, 0, 0)
        picker_calls = []

        target = prompt_target_time(
            now_fn=lambda: now,
            picker_fn=lambda state, current_time: picker_calls.append(
                (state.value, state.selected_field, current_time())
            )
            or selected,
        )

        self.assertEqual(target, selected)
        self.assertEqual(
            picker_calls,
            [(datetime(2026, 8, 14, 9, 0, 0), "day", now)],
        )

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

    def test_revalidates_against_current_time_on_each_retry(self):
        times = iter([
            datetime(2026, 8, 13, 9, 0, 0),
            datetime(2026, 8, 13, 9, 0, 2),
            datetime(2026, 8, 13, 9, 0, 2),
        ])
        prompts = FakeQuestionary(
            text_answers=[
                "2026/08/13 09:00",
                "2026-08-13 09:00:01",
                "2026-08-13 09:00:03",
            ]
        )

        target = prompt_target_time(now_fn=lambda: next(times), questionary_module=prompts)

        self.assertEqual(target, datetime(2026, 8, 13, 9, 0, 3))
        self.assertEqual(len(prompts.text_calls), 3)


class TestCountdownDisplay(unittest.TestCase):
    def test_countdown_updates_replace_the_same_terminal_line(self):
        output = io.StringIO()

        main.render_countdown_status("4일 10:10:39", output=output)
        main.render_countdown_status("4일 10:10:38", output=output)
        main.clear_countdown_status(output=output)

        self.assertEqual(
            output.getvalue(),
            "\r\x1b[2K남은 시간: 4일 10:10:39"
            "\r\x1b[2K남은 시간: 4일 10:10:38"
            "\r\x1b[2K",
        )

    def test_keyboard_interrupt_cancels_countdown_without_propagating(self):
        output = io.StringIO()

        with (
            patch("main.countdown_until", side_effect=KeyboardInterrupt),
            patch("main.log") as log_mock,
        ):
            result = main.run_countdown(
                datetime(2026, 8, 18, 9, 0, 0),
                output=output,
            )

        self.assertFalse(result)
        self.assertTrue(any("취소" in call.args[0] for call in log_mock.call_args_list))
        self.assertTrue(output.getvalue().endswith("\r\x1b[2K"))


class TestCourseRematch(unittest.TestCase):
    def test_rematches_strictly_by_stringified_suup_number(self):
        selected = [{"suupNo": 30012}, {"suupNo": "030012"}, {"suupNo": "30013"}]
        refreshed = [{"suupNo": "30012", "fresh": True}, {"suupNo": "30013", "fresh": True}]

        matched, unresolved = rematch_selected_courses(selected, refreshed)

        self.assertEqual(matched, [refreshed[0], refreshed[1]])
        self.assertEqual(unresolved, [selected[1]])


if __name__ == "__main__":
    unittest.main()
