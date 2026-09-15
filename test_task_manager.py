"""Deterministic checks: validation, persistence, date boundaries and limiter recovery."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
import tempfile
import unittest

from cryptography.fernet import Fernet

from task_manager import (
    AssignmentNotFoundError, DuplicateAssignmentError, InputError,
    RateLimitError, RateLimiter, TaskManager,
)


# Test domain validation, persistence, duplicate control, deletion and rate limits.
class TaskManagerTests(unittest.TestCase):
    # Create isolated temporary storage and dependencies for each test.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.db"
        self.cipher = Fernet(Fernet.generate_key())
        self.manager = TaskManager(self.path, self.cipher, RateLimiter(100), today=lambda: date(2026, 9, 15))

    # Create a standard assignment with optional field overrides for a test.
    def add(self, **changes):
        args = dict(course="ENMGT 5405", title="MCP Assignment", due_date="2026-09-18", estimated_hours=3)
        args.update(changes)
        return self.manager.add_assignment(**args)

    # Verify invalid dates, effort and text never create assignment records.
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

    # Accept a valid leap day and reject one in a non-leap year.
    def test_leap_year_validation(self):
        self.add(due_date="2028-02-29")
        with self.assertRaises(InputError):
            self.add(due_date="2027-02-29")

    # Reject normalized duplicate fields and return the original assignment ID.
    def test_duplicate_rejected_after_text_and_numeric_normalization(self):
        original = self.add()["assignment"]
        with self.assertRaises(DuplicateAssignmentError) as caught:
            self.add(course=" ENMGT 5405 ", title=" MCP Assignment ", estimated_hours=3.0)
        self.assertEqual(caught.exception.existing_id, original["id"])
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 1)

    # Accept assignments that differ in any compared field, including letter case.
    def test_each_changed_field_is_a_distinct_assignment(self):
        self.add()
        for change in [{"course": "Different course"}, {"title": "Different title"},
                       {"due_date": "2026-09-19"}, {"estimated_hours": 3.5},
                       {"title": "mcp assignment"}]:
            self.add(**change)
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 6)

    # Verify independent concurrent connections cannot insert duplicate assignments.
    def test_concurrent_duplicate_requests_insert_only_once(self):
        # Separate managers/connections model multiple processes sharing a database.
        managers = [TaskManager(self.path, self.cipher, RateLimiter(100)) for _ in range(8)]

        # Run one concurrent attempt and report whether the operation was admitted.
        def attempt(manager):
            try:
                manager.add_assignment("ENMGT 5405", "Concurrent", "2026-09-18", 3)
                return True
            except DuplicateAssignmentError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, managers)), 1)
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 1)

    # Preserve historical duplicate rows while rejecting another identical insertion.
    def test_existing_duplicates_are_preserved_and_block_another_insert(self):
        original = self.add()["assignment"]
        with closing(self.manager.connect()) as conn, conn:
            conn.execute("INSERT INTO assignments(course, title, due_date, estimated_hours) VALUES (?, ?, ?, ?)",
                         (self.manager.encrypt(original["course"]), self.manager.encrypt(original["title"]),
                          original["due_date"], original["estimated_hours"]))
        reopened = TaskManager(self.path, self.cipher, today=lambda: date(2026, 9, 15))
        with self.assertRaises(DuplicateAssignmentError):
            reopened.add_assignment(original["course"], original["title"], original["due_date"], 3)
        self.assertEqual(len(reopened.upcoming_assignments()["assignments"]), 2)

    # Verify targeted deletion persists and a later re-add gets a new ID.
    def test_delete_only_specified_record_persists_and_allows_readding(self):
        first = self.add()["assignment"]
        other = self.add(title="Keep this")["assignment"]
        result = self.manager.delete_assignment(first["id"])
        self.assertEqual(result, {"ok": True, "deleted_assignment": first})
        reopened = TaskManager(self.path, self.cipher, today=lambda: date(2026, 9, 15))
        self.assertEqual([row["id"] for row in reopened.upcoming_assignments()["assignments"]], [other["id"]])
        replacement = self.add()["assignment"]
        self.assertGreater(replacement["id"], other["id"])

    # Reject unknown or already-deleted IDs without changing other assignments.
    def test_delete_missing_id_does_not_change_other_records(self):
        original = self.add()["assignment"]
        with self.assertRaises(AssignmentNotFoundError):
            self.manager.delete_assignment(original["id"] + 100)
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 1)
        self.manager.delete_assignment(original["id"])
        with self.assertRaises(AssignmentNotFoundError):
            self.manager.delete_assignment(original["id"])

    # Reject malformed or out-of-range deletion IDs without changing stored data.
    def test_delete_rejects_invalid_ids_without_writes(self):
        self.add()
        for value in [0, -1, True, 1.5, "1", "1 OR 1=1", 2**63, None]:
            with self.subTest(value=value), self.assertRaises(InputError):
                self.manager.delete_assignment(value)
        self.assertEqual(len(self.manager.upcoming_assignments()["assignments"]), 1)

    # Verify duplicate attempts consume capacity and deletion cannot bypass the limit.
    def test_duplicates_and_deletion_share_the_rate_limit(self):
        self.manager.limiter = RateLimiter(2)
        original = self.add()["assignment"]
        with self.assertRaises(DuplicateAssignmentError):
            self.add()
        with self.assertRaises(RateLimitError):
            self.manager.delete_assignment(original["id"])
        with closing(self.manager.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0], 1)

    # Verify restart persistence and that SQL-shaped titles remain harmless data.
    def test_persistence_and_sql_text_is_inert(self):
        payload = "'); DROP TABLE assignments; --"
        self.add(title=payload)
        reopened = TaskManager(self.path, self.cipher, today=lambda: date(2026, 9, 15))
        self.assertEqual(reopened.upcoming_assignments()["assignments"][0]["title"], payload)
        self.add(title="Still works")

    # Check inclusive calendar boundaries, overdue flags and deadline ordering.
    def test_query_date_boundaries_and_order(self):
        for due in ["2026-09-22", "2026-09-21", "2026-09-14", "2026-09-15"]:
            self.add(due_date=due)
        rows = self.manager.upcoming_assignments()["assignments"]
        self.assertEqual([r["due_date"] for r in rows], ["2026-09-14", "2026-09-15", "2026-09-21"])
        self.assertTrue(rows[0]["overdue"])
        self.assertFalse(rows[1]["overdue"])
        self.assertEqual(len(self.manager.upcoming_assignments(days=1, include_overdue=False)["assignments"]), 1)

    # Reject date-window values outside the supported strict integer contract.
    def test_invalid_query_options(self):
        for days in [0, -1, 91, True, 1.5, "7"]:
            with self.subTest(days=days), self.assertRaises(InputError):
                self.manager.upcoming_assignments(days=days)

    # Check actual weekly assignment content and validation of daily capacity.
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

    # Verify tools and prompts share capacity and recover exactly at expiry.
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

    # Verify a rejected business input still consumes an admitted request slot.
    def test_invalid_attempt_consumes_budget(self):
        self.manager.limiter = RateLimiter(1)
        with self.assertRaises(InputError):
            self.add(estimated_hours=-1)
        with self.assertRaises(RateLimitError):
            self.manager.upcoming_assignments()

    # Verify the limiter admits no more concurrent requests than its capacity.
    def test_concurrent_requests_cannot_bypass_limit(self):
        limiter = RateLimiter(3)
        # Run one concurrent attempt and report whether the operation was admitted.
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
