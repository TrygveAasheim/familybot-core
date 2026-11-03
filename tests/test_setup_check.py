import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_setup", ROOT / "scripts" / "check_setup.py")
assert SPEC and SPEC.loader
CHECK_SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_SETUP)


class SetupCheckTests(unittest.TestCase):
    def test_version_parser_accepts_prefixed_versions(self):
        self.assertEqual((22, 23, 2), CHECK_SETUP.version_tuple("v22.23.2"))
        self.assertEqual((2026, 7, 1), CHECK_SETUP.version_tuple("OpenClaw 2026.7.1-2"))
        self.assertIsNone(CHECK_SETUP.version_tuple("unknown"))

    def test_missing_optional_command_warns_without_printing_environment(self):
        with patch.object(CHECK_SETUP, "command_path", return_value=None):
            check, path = CHECK_SETUP.check_command(
                "openclaw", required=False, environment_name="FAMILYBOT_OPENCLAW", remedy="install it"
            )
        self.assertEqual("WARN", check.level)
        self.assertEqual("", "".join(value for value in (check.detail, check.remedy) if "TOKEN" in value))
        self.assertIsNone(path)

    def test_secret_key_check_never_returns_secret_values(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "secrets.env"
            secret_file.write_text("SPOND_USERNAME=user@example.invalid\nSPOND_PASSWORD=do-not-print\n")
            os.chmod(secret_file, 0o600)
            check = CHECK_SETUP.secret_keys_check(
                secret_file, {"SPOND_USERNAME", "SPOND_PASSWORD"}, "Spond credential file"
            )
        self.assertEqual("PASS", check.level)
        self.assertNotIn("do-not-print", check.detail)
        self.assertNotIn("user@example.invalid", check.detail)

    def test_database_check_is_read_only_and_reports_integrity(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "family.db"
            with sqlite3.connect(database) as connection:
                for table in CHECK_SETUP.REQUIRED_CORE_TABLES:
                    connection.execute(f'CREATE TABLE "{table}"(id INTEGER PRIMARY KEY)')
            check = CHECK_SETUP.database_check(database)
        self.assertEqual("PASS", check.level)
        self.assertIn("integrity", check.detail)

    def test_database_check_rejects_an_empty_schema(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "family.db"
            with sqlite3.connect(database):
                pass
            check = CHECK_SETUP.database_check(database)
        self.assertEqual("FAIL", check.level)
        self.assertIn("supported Core schema", check.detail)

    def test_deploy_branch_is_explicitly_overridable_for_forks(self):
        deploy = (ROOT / "scripts/deploy_core.sh").read_text(encoding="utf-8")
        self.assertIn('FAMILYBOT_DEPLOY_BRANCH:-dev', deploy)
        self.assertIn("Expected '$DEPLOY_BRANCH'", deploy)


if __name__ == "__main__":
    unittest.main()
