import os
import sys
import unittest

import questionary
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import (
    classify_registration_result,
    order_courses_by_priority,
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


class TestTicketingRegistration(unittest.TestCase):
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


class TestRegistrationResultClassification(unittest.TestCase):
    def test_success_response_is_not_retried(self):
        self.assertEqual(classify_registration_result("S", "신청 완료"), "success")

    def test_already_registered_response_is_treated_as_success(self):
        self.assertEqual(
            classify_registration_result("E01", "이미 신청된 과목입니다."),
            "success",
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
