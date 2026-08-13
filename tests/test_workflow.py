from datetime import datetime, timedelta
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflow import (
    ScheduleValidationError,
    countdown_until,
    format_remaining,
    parse_target_time,
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


if __name__ == "__main__":
    unittest.main()
