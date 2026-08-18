from __future__ import annotations

import math
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar, Literal, Optional

AttemptStatus = Literal["success", "retry", "blocked"]
CoursePollStatus = Literal["registered", "available", "full", "unknown", "blocked"]


@dataclass
class RegistrationSummary:
    completed: list[dict]
    pending: list[dict]
    interrupted: bool
    blocked: list[dict] = field(default_factory=list)


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
        blocked=[
            state["course"]
            for state in states
            if state["status"] == "blocked"
        ],
    )


def _apply_attempt_result(state, status):
    if status == "success":
        state["status"] = "success"
    elif status == "retry":
        state["status"] = "pending"
    elif status == "blocked":
        state["status"] = "blocked"
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


def run_polling_ticketing(
    courses,
    poll_courses,
    classify_course,
    attempt_course,
    wait_for_next_poll=lambda: None,
    on_poll=None,
) -> RegistrationSummary:
    states = _new_states(courses)
    poll_number = 0

    try:
        while any(state["status"] == "pending" for state in states):
            poll_number += 1
            refreshed_courses = poll_courses()
            refreshed = {
                str(course.get("suupNo")): course
                for course in refreshed_courses
            }
            observations = []
            available = []

            for state in states:
                if state["status"] != "pending":
                    continue
                course = refreshed.get(str(state["course"].get("suupNo")))
                observed_course = course or state["course"]
                poll_status: CoursePollStatus = classify_course(
                    observed_course,
                    refreshed_courses,
                )
                if course is None and poll_status != "blocked":
                    poll_status = "unknown"
                if poll_status not in (
                    "registered",
                    "available",
                    "full",
                    "unknown",
                    "blocked",
                ):
                    raise ValueError(f"알 수 없는 조회 상태: {poll_status}")

                observations.append((observed_course, poll_status))
                if poll_status == "registered":
                    state["course"] = observed_course
                    state["status"] = "success"
                elif poll_status == "blocked":
                    state["course"] = observed_course
                    state["status"] = "blocked"
                elif poll_status == "available":
                    available.append((state, observed_course))

            if on_poll is not None:
                on_poll(poll_number, observations)

            for state, course in available:
                state["attempts"] += 1
                status: AttemptStatus = attempt_course(course, state["attempts"])
                if status == "blocked":
                    state["course"] = course
                    state["status"] = "blocked"
                elif status not in ("success", "retry"):
                    raise ValueError(f"알 수 없는 신청 상태: {status}")

            if any(state["status"] == "pending" for state in states):
                wait_for_next_poll()
    except KeyboardInterrupt:
        return _summary_from_states(states, interrupted=True)

    return _summary_from_states(states)
