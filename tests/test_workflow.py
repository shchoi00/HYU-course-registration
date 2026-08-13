import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow import (
    RegistrationSummary,
    ScheduleValidationError,
    countdown_until,
    format_remaining,
    parse_target_time,
    run_scheduled_pass,
    run_ticketing,
)


class FakeClock:
    def __init__(self, current):
        self.current = current
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


class TestScheduling(unittest.TestCase):
    def test_parse_target_time_rejects_past_value(self):
        now = datetime(2026, 8, 13, 9, 0, 0)

        with self.assertRaisesRegex(ScheduleValidationError, "미래"):
            parse_target_time("2026-08-13 08:59:59", now)

    def test_parse_target_time_rejects_malformed_value(self):
        now = datetime(2026, 8, 13, 9, 0, 0)

        with self.assertRaisesRegex(ScheduleValidationError, "YYYY-MM-DD HH:MM:SS"):
            parse_target_time("2026/08/13 10:00", now)

    def test_parse_target_time_rejects_unpadded_value(self):
        now = datetime(2026, 8, 3, 8, 0, 0)

        with self.assertRaisesRegex(ScheduleValidationError, "YYYY-MM-DD HH:MM:SS"):
            parse_target_time("2026-8-3 9:0:0", now)

    def test_format_remaining_uses_zero_padded_hours_minutes_seconds(self):
        self.assertEqual(format_remaining(3661), "01:01:01")

    def test_countdown_renders_and_waits_until_target(self):
        clock = FakeClock(datetime(2026, 8, 13, 9, 59, 58))
        rendered = []

        countdown_until(
            datetime(2026, 8, 13, 10, 0, 0),
            now_fn=clock.now,
            sleep_fn=clock.sleep,
            render_fn=rendered.append,
        )

        self.assertEqual(rendered, ["00:00:02", "00:00:01", "00:00:00"])
        self.assertEqual(clock.sleeps, [1, 1])


class TestWorkflowModes(unittest.TestCase):
    def setUp(self):
        self.courses = [
            {"haksuNo": "CSE1001", "suupNo": "1", "gwamokNm": "1순위"},
            {"haksuNo": "CSE1002", "suupNo": "2", "gwamokNm": "2순위"},
            {"haksuNo": "CSE1003", "suupNo": "3", "gwamokNm": "3순위"},
        ]

    def test_registration_summary_records_completed_pending_and_interrupt_state(self):
        summary = RegistrationSummary(
            completed=[self.courses[0]],
            pending=[self.courses[1]],
            interrupted=True,
        )

        self.assertEqual(summary.completed, [self.courses[0]])
        self.assertEqual(summary.pending, [self.courses[1]])
        self.assertTrue(summary.interrupted)

    def test_scheduled_pass_attempts_once_and_returns_only_failures(self):
        outcomes = {"1": "retry", "2": "success", "3": "retry"}
        calls = []

        summary = run_scheduled_pass(
            self.courses,
            lambda course, attempt: calls.append((course["suupNo"], attempt))
            or outcomes[course["suupNo"]],
        )

        self.assertEqual(calls, [("1", 1), ("2", 1), ("3", 1)])
        self.assertEqual([course["suupNo"] for course in summary.completed], ["2"])
        self.assertEqual([course["suupNo"] for course in summary.pending], ["1", "3"])
        self.assertFalse(summary.interrupted)

    def test_scheduled_pass_returns_current_and_later_pending_on_keyboard_interrupt(self):
        calls = []

        def attempt(course, attempt_number):
            calls.append((course["suupNo"], attempt_number))
            if course["suupNo"] == "1":
                return "success"
            raise KeyboardInterrupt

        summary = run_scheduled_pass(self.courses, attempt)

        self.assertEqual(calls, [("1", 1), ("2", 1)])
        self.assertEqual([course["suupNo"] for course in summary.completed], ["1"])
        self.assertEqual([course["suupNo"] for course in summary.pending], ["2", "3"])
        self.assertTrue(summary.interrupted)

    def test_ticketing_round_robins_until_all_succeed_without_attempt_cap(self):
        calls = []
        waits = []

        def attempt(course, attempt_number):
            calls.append((course["suupNo"], attempt_number))
            if course["suupNo"] == "1":
                return "success" if attempt_number == 12 else "retry"
            if course["suupNo"] == "2":
                return "success" if attempt_number == 2 else "retry"
            return "success"

        summary = run_ticketing(
            self.courses,
            attempt,
            wait_for_next_round=lambda: waits.append("wait"),
        )

        self.assertIn(("1", 12), calls)
        self.assertEqual(
            calls[:6],
            [("1", 1), ("2", 1), ("3", 1), ("1", 2), ("2", 2), ("1", 3)],
        )
        self.assertEqual(
            [course["suupNo"] for course in summary.completed],
            ["1", "2", "3"],
        )
        self.assertEqual(summary.pending, [])
        self.assertFalse(summary.interrupted)
        self.assertEqual(len(waits), 11)

    def test_ticketing_returns_pending_summary_on_keyboard_interrupt(self):
        calls = []

        def attempt(course, attempt_number):
            calls.append((course["suupNo"], attempt_number))
            if len(calls) == 3:
                raise KeyboardInterrupt
            if course["suupNo"] == "1":
                return "success"
            return "retry"

        summary = run_ticketing(self.courses, attempt)

        self.assertEqual(calls, [("1", 1), ("2", 1), ("3", 1)])
        self.assertEqual([course["suupNo"] for course in summary.completed], ["1"])
        self.assertEqual([course["suupNo"] for course in summary.pending], ["2", "3"])
        self.assertTrue(summary.interrupted)

    def test_ticketing_rejects_unknown_attempt_status(self):
        with self.assertRaisesRegex(ValueError, "알 수 없는 신청 상태"):
            run_ticketing(
                [self.courses[0]],
                lambda _course, _attempt: "failed",
            )


if __name__ == "__main__":
    unittest.main()
