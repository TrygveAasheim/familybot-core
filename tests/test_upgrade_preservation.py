"""Existing-household regression tests: fictional state, never managed deployment."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PORTAL = Path(os.environ.get("FAMILYBOT_TEST_PORTAL_REPO", ROOT.parent / "familybot-portal"))
if not PORTAL.is_dir():
    PORTAL = ROOT / "familybot-portal"
sys.path.insert(0, str(ROOT / "scripts"))

import database_migrations as migrations  # noqa: E402
import install_familybot as installer  # noqa: E402


class UpgradePreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="familybot-upgrade-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "Fiktiv familie Ø"
        self.db = self.workspace / "db/family.db"
        self.config = self.workspace / "config/family.local.json"
        self.backups = self.workspace / "backups"
        self.pin = self.root / "fictional-pin"
        self.pin.write_text("482731\n")
        self.pin.chmod(0o600)
        self.environment = {k: v for k, v in os.environ.items()
                            if not k.startswith("FAMILYBOT_") and k != "OPENCLAW_WORKSPACE"}
        self.environment["FAMILYBOT_WORKSPACE"] = str(self.workspace)
        self.command = [sys.executable, str(ROOT / "scripts/install_familybot.py"),
                        "--workspace", str(self.workspace), "--portal-repo", str(PORTAL),
                        "--demo", "--non-interactive", "--no-deploy", "--parent-pin-source", str(self.pin)]
        result = subprocess.run(self.command, env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def upgrade(self, *options):
        result = subprocess.run(self.command + ["--upgrade", "--writers-stopped", *options],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def scalar(self, query):
        with sqlite3.connect(self.db) as connection:
            return connection.execute(query).fetchone()[0]

    def change_config(self, edit):
        document = json.loads(self.config.read_text())
        edit(document)
        self.config.write_text(json.dumps(document))

    def seed_calendar(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM school_calendar")
            connection.execute("DELETE FROM school_years")
            connection.execute("DELETE FROM norwegian_holidays WHERE kind='school_break'")
            connection.execute("INSERT INTO school_calendar(year_label,event_type,name,start_date,end_date) VALUES('2026/2027','break','Fictional break','2026-10-05','2026-10-09')")
            connection.execute("INSERT OR REPLACE INTO norwegian_holidays VALUES('2026-10-06','Fictional break','school_break')")
            connection.execute("INSERT INTO school_years VALUES('2026/2027','2026-08-17','2027-06-18','Fictional')")

    def test_absent_school_config_preserves_all_legacy_calendar_tables(self):
        self.change_config(lambda doc: doc.pop("school", None))
        self.seed_calendar()
        self.upgrade()
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM school_calendar WHERE name='Fictional break'"))
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM school_years"))
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM norwegian_holidays WHERE kind='school_break'"))

    def test_calendar_replacement_requires_explicit_flag_and_preserves_backup(self):
        self.seed_calendar()
        self.change_config(lambda doc: doc.update(school={"municipality": "Fiktiv kommune", "calendar_events": []}))
        self.upgrade()
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM school_calendar"))
        before = set(self.backups.glob("pre-upgrade-*/family.db"))
        result = self.upgrade("--replace-school-calendar")
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM school_calendar"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM school_years"))
        self.assertIn("[pre-upgrade-backup]", result.stdout)
        created = set(self.backups.glob("pre-upgrade-*/family.db")) - before
        self.assertEqual(1, len(created))
        with sqlite3.connect(created.pop()) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM school_calendar").fetchone()[0])

    def test_upgrade_does_not_seed_archived_chores_or_deactivated_rewards(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE kanban_cards SET archived_at='2026-11-01'")
            connection.execute("UPDATE reward_goals SET active=0")
        count = self.scalar("SELECT COUNT(*) FROM kanban_cards")
        self.upgrade()
        self.upgrade()
        self.assertEqual(count, self.scalar("SELECT COUNT(*) FROM kanban_cards"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM kanban_cards WHERE archived_at IS NULL"))
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM reward_goals WHERE active=1"))

    def test_omitted_member_fields_preserved_and_explicit_null_clears(self):
        def omit(doc):
            for member in doc["members"]:
                for field in ("grade", "school", "teacher"):
                    member.pop(field, None)
        self.change_config(omit)
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE family_members SET grade='4A',school='Fiktiv skole',teacher='Fiktiv lærer' WHERE role='child'")
        self.upgrade()
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM family_members WHERE grade='4A' AND school='Fiktiv skole' AND teacher='Fiktiv lærer'"))
        def clear(doc):
            for member in doc["members"]:
                member["teacher"] = None
        self.change_config(clear)
        self.upgrade()
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM family_members WHERE teacher IS NOT NULL"))
        self.assertEqual(2, self.scalar("SELECT COUNT(*) FROM family_members WHERE grade='4A' AND school='Fiktiv skole'"))

    def test_legacy_pre_migration_backup_restores_without_inventing_markers(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DROP TABLE familybot_schema_migrations")
        result = migrations.apply_migrations(self.db, backup_root=self.backups)
        restored = migrations.restore_database(self.db, Path(result["backup"]), self.backups)
        self.assertTrue(restored["recovery_backup"])
        self.assertEqual(0, self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name='familybot_schema_migrations'"))
        self.assertEqual(4, self.scalar("SELECT COUNT(*) FROM family_members"))
        # The restored legacy state can be upgraded again with the paired tools.
        self.upgrade()
        self.assertEqual(1, self.scalar("SELECT MAX(version) FROM familybot_schema_migrations WHERE component='core'"))
        self.assertEqual(2, self.scalar("SELECT MAX(version) FROM familybot_schema_migrations WHERE component='portal'"))

    def test_backup_failure_prevents_all_upgrade_database_changes(self):
        before = self.db.read_bytes()
        with patch.dict(os.environ, self.environment, clear=True), \
                patch.object(sys, "argv", self.command[1:] + ["--upgrade", "--writers-stopped"]), \
                patch.object(installer, "backup_database", side_effect=migrations.MigrationError("fixture failure")):
            self.assertEqual(1, installer.main())
        self.assertEqual(before, self.db.read_bytes())

    def test_upgrade_keeps_custom_chore_and_awarded_completion_history(self):
        with sqlite3.connect(self.db) as connection:
            card = connection.execute("INSERT INTO kanban_cards(title,assigned_to) VALUES('Fiktiv oppgave','mikkel nordmann')").lastrowid
            connection.execute("INSERT INTO family_chore_meta(card_id,points) VALUES(?,7)", (card,))
            connection.execute("INSERT INTO chore_completions(card_id,member_id,status,points,completed_at,idempotency_key) VALUES(?,3,'awarded',7,'2026-11-01','fictional-history')", (card,))
        self.upgrade()
        self.assertEqual(1, self.scalar("SELECT COUNT(*) FROM kanban_cards WHERE title='Fiktiv oppgave'"))
        self.assertEqual(7, self.scalar("SELECT points FROM chore_completions WHERE idempotency_key='fictional-history'"))

    def test_existing_four_and_five_digit_pins_are_preserved_byte_for_byte(self):
        for pin in ("4827\n", "48273\n"):
            with self.subTest(length=len(pin.strip())):
                self.pin.write_text(pin)
                target = self.workspace / "config/parent-pin.txt"
                target.write_text(pin)
                target.chmod(0o644)
                before = self.config.read_bytes()
                self.upgrade()
                self.assertEqual(pin, target.read_text())
                self.assertEqual(0o600, target.stat().st_mode & 0o777)
                self.assertEqual(before, self.config.read_bytes())

    def test_fresh_install_still_rejects_short_pin(self):
        self.pin.write_text("4827\n")
        with self.assertRaises(installer.InstallError):
            installer.read_pin(self.pin, non_interactive=True)

    def test_existing_database_requires_upgrade_and_stopped_writer_acknowledgement(self):
        for flags in ([], ["--upgrade"]):
            before = self.db.read_bytes()
            result = subprocess.run(self.command + flags, env=self.environment, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertEqual(before, self.db.read_bytes())

    def test_managed_upgrade_preserves_explicit_runtime_and_requires_feature_decisions(self):
        runtime = self.root / "old separate runtime"
        command = [part for part in self.command[1:] if part != "--no-deploy"]
        command += ["--upgrade", "--writers-stopped", "--portal-runtime", str(runtime)]
        with patch.dict(os.environ, self.environment, clear=True), patch.object(sys, "argv", command), \
                patch.object(installer, "deployment_dependencies"), patch.object(installer, "run") as run, \
                patch.object(installer, "verify_local_service"):
            self.assertEqual(0, installer.main())
        deploy = next(call for call in run.call_args_list if call.args[0][-1].endswith("deploy-local.sh"))
        self.assertEqual(str(runtime.resolve()), deploy.kwargs["environment"]["FAMILYBOT_PORTAL_RUNTIME"])
        self.assertEqual(str(self.workspace.resolve()), deploy.kwargs["environment"]["FAMILYBOT_WORKSPACE"])
        self.change_config(lambda doc: doc["portal"]["features"].pop("oda"))
        before = self.db.read_bytes()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(sys, "argv", command), \
                patch.object(installer, "deployment_dependencies"), patch.object(installer, "run") as run:
            self.assertEqual(1, installer.main())
            run.assert_not_called()
        self.assertEqual(before, self.db.read_bytes())

    def test_managed_upgrade_requires_runtime_selection_before_changes(self):
        command = [part for part in self.command[1:] if part != "--no-deploy"]
        before = self.db.read_bytes()
        with patch.dict(os.environ, self.environment, clear=True), \
                patch.object(sys, "argv", command + ["--upgrade", "--writers-stopped"]), \
                patch.object(installer, "deployment_dependencies") as dependencies:
            self.assertEqual(1, installer.main())
            dependencies.assert_not_called()
        self.assertEqual(before, self.db.read_bytes())

    def test_restore_refuses_sidecars_and_unrelated_database_without_touching_target(self):
        backup = migrations.backup_database(self.db, self.backups)
        sidecar = Path(str(self.db) + "-wal")
        sidecar.write_bytes(b"fictional sidecar sentinel")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(migrations.MigrationError, "Stop all database users"):
            migrations.restore_database(self.db, backup, self.backups)
        self.assertEqual(before, self.db.read_bytes())
        sidecar.unlink()
        unrelated = self.root / "unrelated.db"
        with sqlite3.connect(unrelated) as connection:
            connection.execute("CREATE TABLE unrelated(id INTEGER)")
        with self.assertRaises(migrations.MigrationError):
            migrations.restore_database(self.db, unrelated, self.backups)
        self.assertEqual(before, self.db.read_bytes())

    def test_restore_rejects_future_or_tampered_core_history(self):
        for change in ("UPDATE familybot_schema_migrations SET version=99 WHERE component='core'",
                       "UPDATE familybot_schema_migrations SET checksum='wrong' WHERE component='core'"):
            backup = migrations.backup_database(self.db, self.backups)
            with sqlite3.connect(backup) as connection:
                connection.execute(change)
            before = self.db.read_bytes()
            with self.assertRaises(migrations.MigrationError):
                migrations.restore_database(self.db, backup, self.backups)
            self.assertEqual(before, self.db.read_bytes())

    def test_restore_cli_requires_stopped_writer_acknowledgement(self):
        backup = migrations.backup_database(self.db, self.backups)
        before = self.db.read_bytes()
        command = [sys.executable, str(ROOT / "scripts/manage_database.py"), "restore",
                   "--db", str(self.db), "--backup-root", str(self.backups), "--from-backup", str(backup)]
        result = subprocess.run(command, env=self.environment, capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("--writers-stopped", result.stdout + result.stderr)
        self.assertEqual(before, self.db.read_bytes())
        result = subprocess.run(command + ["--writers-stopped"], env=self.environment,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(4, self.scalar("SELECT COUNT(*) FROM family_members"))


if __name__ == "__main__":
    unittest.main()
