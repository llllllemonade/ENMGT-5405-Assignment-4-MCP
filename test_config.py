"""Verify real .env secret use, encryption and fail-closed key handling."""

from contextlib import closing, redirect_stdout
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from config import ConfigurationError, load_settings
from init_local import initialize
from task_manager import StorageError, TaskManager


class ConfigurationAndStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = io.StringIO()
        with redirect_stdout(self.output):
            initialize(self.root)
        self.settings = load_settings(self.root / ".env")

    def test_generated_secret_is_not_printed_or_replaced(self):
        before = (self.root / ".env").read_bytes()
        with redirect_stdout(self.output):
            self.assertFalse(initialize(self.root))
        self.assertEqual(before, (self.root / ".env").read_bytes())
        self.assertNotIn(self.settings.data_key, self.output.getvalue())
        self.assertNotIn(self.settings.data_key, repr(self.settings))

    def test_system_secret_does_not_override_dotenv(self):
        with patch.dict("os.environ", {"TASK_DATA_KEY": "wrong-system-value", "TASK_RATE_LIMIT": "999"}):
            settings = load_settings(self.root / ".env")
        self.assertEqual(settings.data_key, self.settings.data_key)
        self.assertEqual(settings.rate_limit, 10)

    def test_missing_or_invalid_secret_fails_without_disclosing_value(self):
        with self.assertRaises(ConfigurationError):
            load_settings(self.root / "absent.env")
        bad_secret = "private-but-invalid-secret"
        (self.root / ".env").write_text(f"TASK_DATA_KEY={bad_secret}\n", encoding="utf-8")
        with self.assertRaises(ConfigurationError) as caught:
            load_settings(self.root / ".env")
        self.assertNotIn(bad_secret, str(caught.exception))

    def test_relative_database_path_uses_dotenv_directory(self):
        self.assertEqual(self.settings.db_path, (self.root / "data/assignments_secure.db").resolve())

    def test_invalid_rate_settings_are_rejected(self):
        key_line = f"TASK_DATA_KEY={self.settings.data_key}\n"
        for bad in ("TASK_RATE_LIMIT=0", "TASK_RATE_WINDOW_SECONDS=nan", "TASK_RATE_WINDOW_SECONDS=-1"):
            (self.root / ".env").write_text(key_line + bad + "\n", encoding="utf-8")
            with self.subTest(setting=bad), self.assertRaises(ConfigurationError):
                load_settings(self.root / ".env")

    def test_plaintext_is_absent_and_original_key_reopens_database(self):
        cipher = Fernet(self.settings.data_key.encode("ascii"))
        manager = TaskManager(self.settings.db_path, cipher)
        manager.add_assignment("Private Course", "Private Assignment", date.today().isoformat(), 2)
        with closing(manager.connect()) as conn:
            raw = dict(conn.execute("SELECT * FROM assignments").fetchone())
        self.assertNotEqual(raw["course"], "Private Course")
        self.assertNotEqual(raw["title"], "Private Assignment")
        self.assertNotIn(b"Private Assignment", self.settings.db_path.read_bytes())
        reopened = TaskManager(self.settings.db_path, cipher)
        self.assertEqual(reopened.upcoming_assignments()["assignments"][0]["title"], "Private Assignment")
        with self.assertRaises(StorageError):
            TaskManager(self.settings.db_path, Fernet(Fernet.generate_key()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
