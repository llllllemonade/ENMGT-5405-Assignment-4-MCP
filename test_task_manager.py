"""Deterministic checks: validation, persistence, date boundaries and limiter recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import tempfile
import unittest

from cryptography.fernet import Fernet

from task_manager import InputError, RateLimitError, RateLimiter, StorageError, TaskManager


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.db"
        self.cipher = Fernet(Fernet.generate_key())
        self.manager = TaskManager(self.path, self.cipher, RateLimiter(100), today=lambda: date(2026, 9, 15))

    def add(self, **changes):
        args = dict(course="ENMGT 5405", title="MCP Assignment", due_date="2026-09-18", estimated_hours=3)
        args.update(changes)
        return self.manager.add_assignment(**args)

    def test_invalid_inputs_do_not_write(self):
        for changes in [
            {"due_date": "2026-02-30"}, {"due_date": "2026-2-03"},
            {"due_date": "2026-01-01'; DROP TABLE assignments;--"},
            {"estimated_hours": -2}, {"estimated_hours": 0},
            {"estimated_hours": float("nan")}, {"estimated_hours": float("inf")},
            {"estimated_hours": True}, {"estimated_hours": 1001},
            {"course": " "}, {"title": "x" * 201}, {"title": "bad\nname"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(InputError):
                self.add(**changes)
        self.assertEqual(self.manager.upcoming_assignments()["assignments"], [])

    def test_leap_year_validation(self):
        self.add(due_date="2028-02-29")
        with self.assertRaises(InputError):
            self.add(due_date="2027-02-29")

    def test_persistence_and_sql_text_is_inert(self):
        payload = "'); DROP TABLE assignments; --"
        self.add(title=payload)
        reopened = TaskManager(self.path, self.cipher, today=lambda: date(2026, 9, 15))
        self.assertEqual(reopened.upcoming_assignments()["assignments"][0]["title"], payload)
        self.add(title="Still works")

    def test_query_date_boundaries_and_order(self):
        for due in ["2026-09-22", "2026-09-21", "2026-09-14", "2026-09-15"]:
            self.add(due_date=due)
        rows = self.manager.upcoming_assignments()["assignments"]
        self.assertEqual([r["due_date"] for r in rows], ["2026-09-14", "2026-09-15", "2026-09-21"])
        self.assertTrue(rows[0]["overdue"])
        self.assertFalse(rows[1]["overdue"])
        self.assertEqual(len(self.manager.upcoming_assignments(days=1, include_overdue=False)["assignments"]), 1)

    def test_invalid_query_options(self):
        for days in [0, -1, 91, True, 1.5, "7"]:
            with self.subTest(days=days), self.assertRaises(InputError):
                self.manager.upcoming_assignments(days=days)

    def test_prompt_uses_calendar_week_and_real_data(self):
        self.add(title="This week", due_date="2026-09-20")
        self.add(title="Next week", due_date="2026-09-21")
        prompt = self.manager.weekly_study_plan("1.5")
        self.assertIn("2026-09-20", prompt)
        self.assertIn("This week", prompt)
        self.assertNotIn("Next week", prompt)
        self.assertIn("1.5", prompt)
        for budget in ["-1", "0", "nan", "inf", "25", "bad"]:
            with self.subTest(budget=budget), self.assertRaises(InputError):
                self.manager.weekly_study_plan(budget)

    def test_limit_shared_by_tools_and_prompt_and_recovers(self):
        now = [0.0]
        self.manager.limiter = RateLimiter(3, 60, clock=lambda: now[0])
        self.add()
        self.manager.upcoming_assignments()
        self.manager.weekly_study_plan()
        with self.assertRaises(RateLimitError):
            self.add(title="Must not be saved")
        now[0] = 59.9
        with self.assertRaises(RateLimitError):
            self.manager.upcoming_assignments()
        now[0] = 60.0
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 1)

    def test_invalid_attempt_consumes_budget(self):
        self.manager.limiter = RateLimiter(1)
        with self.assertRaises(InputError):
            self.add(estimated_hours=-1)
        with self.assertRaises(RateLimitError):
            self.manager.upcoming_assignments()

    def test_concurrent_requests_cannot_bypass_limit(self):
        limiter = RateLimiter(3)
        def attempt(_):
            try:
                limiter.check()
                return True
            except RateLimitError:
                return False
        with ThreadPoolExecutor(max_workers=10) as pool:
            self.assertEqual(sum(pool.map(attempt, range(20))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
