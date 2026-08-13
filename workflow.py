from __future__ import annotations

import math
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Literal, Optional

AttemptStatus = Literal["success", "retry"]


@dataclass
class RegistrationSummary:
    completed: list[dict]
    pending: list[dict]
    interrupted: bool


class ScheduleValidationError(ValueError):
    pass


@dataclass
class DateTimePickerState:
    value: datetime
    selected_index: int = 2
    error: Optional[str] = None  # noqa: UP045

    FIELDS: ClassVar[tuple[str, ...]] = (
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
    )

    @classmethod
    def for_now(cls, now: datetime):
        return cls(now.replace(hour=9, minute=0, second=0, microsecond=0))

    @property
    def selected_field(self):
        return self.FIELDS[self.selected_index]

    def move(self, offset: int) -> None:
        self.selected_index = (self.selected_index + offset) % len(self.FIELDS)

    def adjust(self, offset: int) -> None:
        field = self.selected_field
        if field == "year":
            year = min(9999, max(1, self.value.year + offset))
            self.value = self._replace_date(year=year, month=self.value.month)
        elif field == "month":
            absolute_month = (self.value.year - 1) * 12 + self.value.month - 1 + offset
            absolute_month = min(9999 * 12 - 1, max(0, absolute_month))
            year, month_index = divmod(absolute_month, 12)
            self.value = self._replace_date(year=year + 1, month=month_index + 1)
        elif field == "day":
            try:
                self.value += timedelta(days=offset)
            except (OverflowError, ValueError):
                pass
        elif field == "hour":
            self.value = self.value.replace(hour=(self.value.hour + offset) % 24)
        elif field == "minute":
            self.value = self.value.replace(minute=(self.value.minute + offset) % 60)
        else:
            self.value = self.value.replace(second=(self.value.second + offset) % 60)
        self.error = None

    def confirm(self, now: datetime):
        if self.value <= now:
            self.error = "예약 시간은 현재보다 미래여야 합니다."
            return None
        self.error = None
        return self.value

    def _replace_date(self, year: int, month: int):
        day = min(self.value.day, monthrange(year, month)[1])
        return self.value.replace(year=year, month=month, day=day)


def parse_target_time(value: str, now: datetime) -> datetime:
    try:
        target = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ScheduleValidationError(
            "시간은 YYYY-MM-DD HH:MM:SS 형식으로 입력해야 합니다."
        ) from exc

    if target.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise ScheduleValidationError(
            "시간은 YYYY-MM-DD HH:MM:SS 형식으로 입력해야 합니다."
        )

    if target <= now:
        raise ScheduleValidationError("예약 시간은 현재보다 미래여야 합니다.")

    return target


def format_remaining(seconds: float) -> str:
    whole_seconds = max(0, int(seconds))
    days, remainder = divmod(whole_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}일 {hours:02d}:{minutes:02d}:{seconds:02d}"
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


def _new_states(courses):
    return [
        {"course": course, "attempts": 0, "status": "pending"}
        for course in courses
    ]


def _summary_from_states(states, interrupted=False):
    return RegistrationSummary(
        completed=[
            state["course"]
            for state in states
            if state["status"] == "success"
        ],
        pending=[
            state["course"]
            for state in states
            if state["status"] == "pending"
        ],
        interrupted=interrupted,
    )


def _apply_attempt_result(state, status):
    if status == "success":
        state["status"] = "success"
    elif status == "retry":
        state["status"] = "pending"
    else:
        raise ValueError(f"알 수 없는 신청 상태: {status}")


def run_scheduled_pass(courses, attempt_course) -> RegistrationSummary:
    states = _new_states(courses)

    try:
        for state in states:
            state["attempts"] += 1
            status: AttemptStatus = attempt_course(state["course"], state["attempts"])
            _apply_attempt_result(state, status)
    except KeyboardInterrupt:
        return _summary_from_states(states, interrupted=True)

    return _summary_from_states(states)


def run_ticketing(
    courses,
    attempt_course,
    wait_for_next_round=lambda: None,
) -> RegistrationSummary:
    states = _new_states(courses)

    try:
        while True:
            pending = [
                state
                for state in states
                if state["status"] == "pending"
            ]
            if not pending:
                break

            for state in pending:
                state["attempts"] += 1
                status: AttemptStatus = attempt_course(
                    state["course"],
                    state["attempts"],
                )
                _apply_attempt_result(state, status)

            if any(state["status"] == "pending" for state in states):
                wait_for_next_round()
    except KeyboardInterrupt:
        return _summary_from_states(states, interrupted=True)

    return _summary_from_states(states)
