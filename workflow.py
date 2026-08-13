from dataclasses import dataclass
from datetime import datetime
import math
from typing import Literal


AttemptStatus = Literal["success", "retry"]


@dataclass
class RegistrationSummary:
    completed: list[dict]
    pending: list[dict]
    interrupted: bool


class ScheduleValidationError(ValueError):
    pass


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
