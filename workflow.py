from datetime import datetime
import math


class ScheduleValidationError(ValueError):
    pass


def parse_target_time(value: str, now: datetime) -> datetime:
    try:
        target = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ScheduleValidationError(
            "시간은 YYYY-MM-DD HH:MM:SS 형식으로 입력해야 합니다."
        ) from exc

    if target <= now:
        raise ScheduleValidationError("예약 시간은 현재보다 미래여야 합니다.")

    return target


def format_remaining(seconds: float) -> str:
    whole_seconds = max(0, int(seconds))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def countdown_until(target, now_fn, sleep_fn, render_fn) -> None:
    last_displayed = None

    while True:
        remaining = (target - now_fn()).total_seconds()
        whole_seconds = max(0, math.ceil(remaining))

        if whole_seconds != last_displayed:
            render_fn(format_remaining(whole_seconds))
            last_displayed = whole_seconds

        if remaining <= 0:
            return

        sleep_fn(min(remaining, 1))
