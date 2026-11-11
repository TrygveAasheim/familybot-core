"""Fictional pre-ledger routing schema, not a current schema with its ledger removed."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import database_migrations as migrations  # noqa: E402

from tests.test_database_migrations import fictional_config  # noqa: E402

LEGACY_ROUTING = """
CREATE TABLE routing_audit (
    id INTEGER PRIMARY KEY,
    message_id TEXT,
    subject TEXT,
    raw_sender TEXT,
    matched_rule_id INTEGER REFERENCES email_senders(id),
    resolved_member_id INTEGER REFERENCES family_members(id),
    resolved_category TEXT,
    confidence TEXT,
    notes TEXT,
    routed_at TEXT DEFAULT (datetime('now'))
);
INSERT INTO routing_audit(message_id,subject,resolved_category,confidence)
VALUES('fixture-unknown','Fictional message','unknown','fallback'),
      ('fixture-school','Fictional school','school','exact');
"""


class LegacyRoutingAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'family.db'
        self.backups = self.root / 'backups'
        self.config = fictional_config(self.root / 'family.json')
        with sqlite3.connect(self.database) as db:
            db.executescript(LEGACY_ROUTING)

    def snapshot(self, database=None):
        with sqlite3.connect(database or self.database) as db:
            return (db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),
                    db.execute('SELECT * FROM routing_audit ORDER BY id').fetchall())

    def test_adopts_real_legacy_shape_preserves_history_and_is_repeatable(self):
        before = self.snapshot()
        checksum = migrations.CORE_MIGRATIONS[0].checksum
        result = migrations.initialize_database(self.database, self.config, self.backups)
        with sqlite3.connect(self.database) as db:
            old_columns = [row[1] for row in db.execute('PRAGMA table_info(routing_audit)') if row[1] != 'quarantine']
            self.assertEqual(before[1], db.execute('SELECT '+','.join(old_columns)+' FROM routing_audit ORDER BY id').fetchall())
            self.assertEqual([(None,), (None,)], db.execute('SELECT quarantine FROM routing_audit ORDER BY id').fetchall())
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE routing_audit SET quarantine=2')
            self.assertEqual(checksum, db.execute("SELECT checksum FROM familybot_schema_migrations WHERE component='core'").fetchone()[0])
        self.assertEqual(before, self.snapshot(Path(result['backup'])))
        after = self.snapshot()
        self.assertEqual([], migrations.initialize_database(self.database, self.config, self.backups)['applied'])
        self.assertEqual(after, self.snapshot())
        self.assertTrue(migrations.migration_status(self.database)['current'])

    def test_validation_failure_rolls_back_column_and_ledger(self):
        before = self.snapshot()
        with patch.object(migrations, 'validate_core_schema', side_effect=migrations.MigrationError('fixture failure')):
            with self.assertRaises(migrations.MigrationError):
                migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(list(self.backups.glob('core-migration-*/family.db')))

    def test_backup_failure_prevents_adoption(self):
        before = self.snapshot()
        with patch.object(migrations, 'backup_database', side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):
                migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())

    def test_unknown_shape_is_not_repaired(self):
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE routing_audit DROP COLUMN notes')
        before = self.snapshot()
        with self.assertRaises(migrations.MigrationError):
            migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())

    def test_wrong_legacy_column_type_is_not_adopted(self):
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE routing_audit DROP COLUMN notes')
            db.execute('ALTER TABLE routing_audit ADD COLUMN notes INTEGER')
        before = self.snapshot()
        with self.assertRaises(migrations.MigrationError):
            migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())

    def test_composite_primary_key_is_not_a_known_legacy_shape(self):
        with sqlite3.connect(self.database) as db:
            db.execute('DROP TABLE routing_audit')
            db.executescript(LEGACY_ROUTING.replace('id INTEGER PRIMARY KEY,', 'id INTEGER,').replace(
                "routed_at TEXT DEFAULT (datetime('now'))",
                "routed_at TEXT DEFAULT (datetime('now')), PRIMARY KEY(id,message_id)"))
        before = self.snapshot()
        with self.assertRaises(migrations.MigrationError):
            migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())

    def test_existing_flag_values_and_extensions_are_preserved(self):
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE routing_audit ADD COLUMN quarantine INTEGER')
            db.execute('ALTER TABLE routing_audit ADD COLUMN household_extension TEXT')
            db.execute("UPDATE routing_audit SET quarantine=1,household_extension='retained' WHERE id=1")
        before = self.snapshot()[1]
        migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot()[1])

    def test_ledger_does_not_authorize_repair_of_a_damaged_versioned_database(self):
        migrations.initialize_database(self.database, self.config, self.backups)
        with sqlite3.connect(self.database) as db:
            db.execute('ALTER TABLE routing_audit DROP COLUMN quarantine')
        before = self.snapshot()
        with self.assertRaises(migrations.MigrationError):
            migrations.apply_migrations(self.database, backup_root=self.backups)
        self.assertEqual(before, self.snapshot())

    def test_restore_recovers_unversioned_shape_and_original_rows(self):
        # Restore requires a recognizable complete family database. These three
        # minimal legacy tables are authored here, not obtained from a household.
        with sqlite3.connect(self.database) as db:
            db.executescript('''
                CREATE TABLE family_members(id INTEGER PRIMARY KEY,name TEXT,role TEXT,grade TEXT,school TEXT,teacher TEXT);
                CREATE TABLE kanban_cards(id INTEGER PRIMARY KEY,title TEXT,assigned_to TEXT,lane TEXT,priority TEXT,archived_at TEXT,created_at TEXT);
                CREATE TABLE week_plans(id INTEGER PRIMARY KEY,member_id INTEGER,week_number INTEGER,year INTEGER,raw_text TEXT,created_at TEXT);
            ''')
        before = self.snapshot()
        result = migrations.apply_migrations(self.database, backup_root=self.backups)
        migrations.restore_database(self.database, Path(result['backup']), self.backups)
        self.assertEqual(before, self.snapshot())

    def test_new_decisions_record_flags_on_fresh_and_adopted_schema(self):
        import email_routing
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                database = self.database if legacy else self.root / 'fresh.db'
                migrations.initialize_database(database, self.config, self.backups)
                with patch.object(email_routing, 'DB_PATH', str(database)):
                    for flag in (True, False):
                        decision = email_routing.RoutingResult(None, None, 'unknown' if flag else 'school',
                                                               'fallback', None, 'Fictional', flag)
                        with patch.object(email_routing, '_do_resolve', return_value=decision):
                            for _ in range(2):
                                email_routing.resolve_sender(f'new-{flag}', 'Fictional', 'test@example.invalid', 'Test')
                    with sqlite3.connect(database) as db:
                        self.assertEqual([('new-False', 0), ('new-True', 1)], db.execute(
                            "SELECT message_id,quarantine FROM routing_audit WHERE message_id LIKE 'new-%' ORDER BY message_id").fetchall())
                    self.assertEqual(1, len(email_routing.get_quarantined()))
                    if legacy:
                        unknown = email_routing.RoutingResult(None, None, 'unknown', 'fallback', None, 'Fictional', True)
                        with patch.object(email_routing, '_do_resolve', return_value=unknown):
                            email_routing.resolve_sender('fixture-unknown', 'Fictional', 'test@example.invalid', 'Test')
                        with sqlite3.connect(database) as db:
                            self.assertIsNone(db.execute("SELECT quarantine FROM routing_audit WHERE message_id='fixture-unknown'").fetchone()[0])

    def test_new_writer_retains_unversioned_schema_compatibility(self):
        import email_routing
        with sqlite3.connect(self.database) as db:
            db.executescript('CREATE TABLE family_members(id INTEGER PRIMARY KEY); CREATE TABLE email_senders(id INTEGER PRIMARY KEY);')
        with patch.object(email_routing, 'DB_PATH', str(self.database)), \
                patch.object(email_routing, '_do_resolve', return_value=email_routing.RoutingResult(
                    None, None, 'unknown', 'fallback', None, 'Fictional', True)):
            email_routing.resolve_sender('new-legacy', 'Fictional', 'test@example.invalid', 'Test')
        self.assertEqual(3, len(self.snapshot()[1]))
