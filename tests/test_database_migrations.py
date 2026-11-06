from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from database_migrations import (  # noqa: E402
    CORE_SCHEMA_VERSION,
    Migration,
    MigrationError,
    apply_migrations,
    backup_database,
    connect,
    initialize_database,
    migration_status,
    restore_database,
    schema_version,
)


def fictional_config(path: Path, *, parent_name: str = "Nora Nordmann") -> Path:
    document = {
        "schema_version": 1,
        "profile": "dashboard",
        "family": {"display_name": "Familien Nordlys", "locale": "nb-NO", "timezone": "Europe/Oslo"},
        "portal": {
            "hostname": "familie.local",
            "web_port": 3000,
            "api_port": 8788,
            "bonjour_name": "Familieportalen",
            "allowed_origins": ["http://familie.local:3000"],
            "features": {"oda": False, "oda_ai": False, "hellofresh": False, "hellofresh_account": False},
        },
        "members": [
            {"member_id": 1, "role": "parent", "name": parent_name, "slug": "nora"},
            {
                "member_id": 2,
                "role": "child",
                "name": "Mikkel Nordmann",
                "slug": "mikkel",
                "avatar": "🦊",
                "grade": "4A",
            },
        ],
        "integrations": {},
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    return path


class DatabaseMigrationTests(unittest.TestCase):
    def test_fresh_initialization_is_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"

            first = initialize_database(database, config, backups)
            second = initialize_database(database, config, backups)

            self.assertEqual([1], first["applied"])
            self.assertEqual(2, first["members_created"])
            self.assertEqual([], second["applied"])
            self.assertEqual(0, second["members_created"])
            self.assertEqual(0o600, database.stat().st_mode & 0o777)
            with connect(database) as connection:
                self.assertEqual(CORE_SCHEMA_VERSION, schema_version(connection))
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM family_members").fetchone()[0])
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(
                {
                    "calendar_events",
                    "email_processing_state",
                    "family_members",
                    "kanban_cards",
                    "week_plan_interpretations",
                    "week_plans",
                }
                <= tables
            )
            self.assertTrue(migration_status(database)["current"])

    def test_legacy_baseline_is_backed_up_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            with connect(database) as connection:
                connection.execute("INSERT INTO kanban_cards(title,assigned_to) VALUES('Ta ut papir','nora')")
                connection.execute("DROP TABLE familybot_schema_migrations")

            result = apply_migrations(database, backup_root=backups)

            self.assertEqual([1], result["applied"])
            self.assertIsNotNone(result["backup"])
            backup = Path(result["backup"])
            self.assertTrue(backup.is_file())
            self.assertEqual(0o600, backup.stat().st_mode & 0o777)
            with connect(backup) as connection:
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='familybot_schema_migrations'"
                    ).fetchone()
                )
            with connect(database) as connection:
                title = connection.execute("SELECT title FROM kanban_cards").fetchone()[0]
            self.assertEqual("Ta ut papir", title)

    def test_failed_migration_rolls_back_and_keeps_recovery_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            with connect(database) as connection:
                connection.execute("INSERT INTO kanban_cards(title,assigned_to) VALUES('Behold meg','nora')")

            def fail_after_write(connection: sqlite3.Connection) -> None:
                connection.execute("CREATE TABLE must_rollback(id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO must_rollback(id) VALUES(1)")
                raise RuntimeError("simulated interruption")

            migration = Migration(2, "simulated-failure", fail_after_write, "test-only")
            with self.assertRaises(MigrationError):
                apply_migrations(database, backup_root=backups, migrations=(migration,))

            with connect(database) as connection:
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='must_rollback'"
                    ).fetchone()
                )
                self.assertEqual("Behold meg", connection.execute("SELECT title FROM kanban_cards").fetchone()[0])
                self.assertEqual(1, schema_version(connection))
            self.assertTrue(list(backups.glob("core-migration-*/family.db")))

    def test_member_name_and_profile_changes_preserve_identity_and_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            with connect(database) as connection:
                connection.execute(
                    "INSERT INTO kanban_cards(title,assigned_to) VALUES('Behold oppgaven','nora nordmann')"
                )
            changed = fictional_config(root / "changed.json", parent_name="Nora Nyttnavn")

            result = initialize_database(database, changed, backups)

            self.assertEqual(1, result["members_updated"])
            self.assertIn("core-profile-", str(result["backup"]))
            with connect(database) as connection:
                name = connection.execute("SELECT name FROM family_members WHERE id=1").fetchone()[0]
                assigned = connection.execute("SELECT assigned_to FROM kanban_cards").fetchone()[0]
            self.assertEqual("Nora Nyttnavn", name)
            self.assertEqual("nora nyttnavn", assigned)

    def test_member_role_change_is_rejected_without_rewriting_household(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            value = json.loads(config.read_text(encoding="utf-8"))
            value["members"][0]["role"] = "child"
            conflicting = root / "conflict.json"
            conflicting.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(MigrationError):
                initialize_database(database, conflicting, backups)

            with connect(database) as connection:
                role = connection.execute("SELECT role FROM family_members WHERE id=1").fetchone()[0]
            self.assertEqual("parent", role)

    def test_manual_backup_is_private_and_integrity_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)

            backup = backup_database(database, backups, label="manual")

            self.assertEqual(0o600, backup.stat().st_mode & 0o777)
            with connect(backup) as connection:
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])

    def test_restore_preserves_a_recovery_copy_and_replaces_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            with connect(database) as connection:
                connection.execute(
                    "INSERT INTO kanban_cards(title,assigned_to) VALUES('Original','nora')"
                )
            source = backup_database(database, backups, label="manual")
            with connect(database) as connection:
                connection.execute("UPDATE kanban_cards SET title='Changed'")

            result = restore_database(database, source, backups)

            self.assertIsNotNone(result["recovery_backup"])
            with connect(database) as connection:
                self.assertEqual(
                    "Original", connection.execute("SELECT title FROM kanban_cards").fetchone()[0]
                )
            with connect(Path(result["recovery_backup"])) as connection:
                self.assertEqual(
                    "Changed", connection.execute("SELECT title FROM kanban_cards").fetchone()[0]
                )

    def test_restore_rejects_invalid_source_before_touching_current_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "workspace/db/family.db"
            config = fictional_config(root / "family.json")
            backups = root / "workspace/backups"
            initialize_database(database, config, backups)
            invalid = root / "invalid.db"
            invalid.write_bytes(b"not sqlite")
            with self.assertRaises(MigrationError):
                restore_database(database, invalid, backups)
            with connect(database) as connection:
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM family_members").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
