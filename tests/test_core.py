import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
os.environ["FAMILYBOT_FAMILY_CONFIG"] = os.path.join(
    os.path.dirname(__file__), "fixtures", "family.test.json"
)

import briefing
import briefing_data
from calendar_guard import validate_event, week_date_range
from email_routing import _resolve_member_from_body
from reliability import DeliveryOutbox, EmailProcessingLedger, atomic_write_json


class CalendarGuardTests(unittest.TestCase):
    def test_iso_week_range(self):
        self.assertEqual(week_date_range(34, 2026), (date(2026, 8, 17), date(2026, 8, 21)))

    def test_rejects_wrong_week(self):
        result = validate_event("test", date(2026, 8, 24), stated_week=34, year=2026)
        self.assertFalse(result.ok)

    def test_accepts_future_reference(self):
        result = validate_event("test", date(2026, 8, 24), stated_week=34,
                                year=2026, future_week_ref=True)
        self.assertTrue(result.ok)


class CurrentClassRoutingTests(unittest.TestCase):
    def test_3a_routes_to_child_one(self):
        self.assertEqual(_resolve_member_from_body("Til 3A: ukeplan uke 34"), 3)

    def test_6a_routes_to_child_two(self):
        self.assertEqual(_resolve_member_from_body("Til 6A: ukeplan uke 34"), 4)


class BriefingTimeDimensionTests(unittest.TestCase):
    def test_weekend_daily_briefing_uses_next_weeks_plan(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        try:
            conn = sqlite3.connect(handle.name)
            conn.executescript("""
                CREATE TABLE norwegian_holidays (date TEXT, name TEXT);
                CREATE TABLE calendar_events (
                    title TEXT, event_time TEXT, member_id INTEGER, bring TEXT,
                    description TEXT, requires_response INTEGER, location TEXT,
                    source TEXT, event_date TEXT
                );
                CREATE TABLE activities (
                    member_id INTEGER, name TEXT, schedule TEXT, notes TEXT,
                    active INTEGER, paused_until TEXT
                );
                CREATE TABLE kanban_cards (
                    title TEXT, priority TEXT, due_date TEXT, description TEXT,
                    lane TEXT, archived_at TEXT, assigned_to TEXT
                );
                CREATE TABLE spond_events (
                    title TEXT, event_date TEXT, group_name TEXT, member_id INTEGER,
                    requires_response INTEGER
                );
                CREATE TABLE week_plans (
                    summary TEXT, teacher TEXT, raw_text TEXT, member_id INTEGER,
                    week_number INTEGER, year INTEGER, created_at TEXT
                );
                INSERT INTO week_plans VALUES
                    ('Child One week 34', 'Teacher', 'Wednesday: bring backpack', 3, 34, 2026, '2026-08-15');
            """)
            conn.commit()
            conn.close()

            fake_met = {
                "weather": {"summary": "test"},
                "aqi": {"label": "test"},
                "pollen": [],
            }
            with mock.patch.object(briefing_data, "DB_PATH", handle.name), \
                 mock.patch.object(briefing_data, "fetch_met_data", return_value=fake_met), \
                 mock.patch.object(briefing_data, "fetch_tbane_status", return_value=[]):
                daily = briefing_data.collect_daily(date(2026, 8, 15))

            self.assertEqual(daily["week"], 33)
            self.assertEqual(daily["ukeplan_week"], 34)
            self.assertEqual(daily["ukeplaner"]["child_1"]["summary"], "Child One week 34")
        finally:
            os.unlink(handle.name)


class DeliverySafetyTests(unittest.TestCase):
    def test_vacation_mode_blocks_telegram(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            json.dump({"enabled": True}, handle)
            path = handle.name
        try:
            with mock.patch.object(briefing, "VACATION_MODE_FILE", path), \
                mock.patch("briefing.subprocess.run") as runner:
                self.assertFalse(briefing.send_telegram("test", "message"))
                runner.assert_not_called()
        finally:
            os.unlink(path)


class DeliveryOutboxTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        self.db_path = handle.name
        self.now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
        self.outbox = DeliveryOutbox(self.db_path, clock=lambda: self.now)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_enqueue_is_idempotent_and_updates_pending_payload(self):
        first = self.outbox.enqueue(
            idempotency_key="daily:2026-08-15:parent_1",
            target="parent_1",
            payload="first",
            kind="daily",
        )
        second = self.outbox.enqueue(
            idempotency_key="daily:2026-08-15:parent_1",
            target="parent_1",
            payload="corrected",
            kind="daily",
        )
        self.assertEqual(first, second)
        self.assertEqual(self.outbox.counts()["pending"], 1)
        seen = []
        result = self.outbox.deliver_pending(lambda target, payload: seen.append(payload) or True)
        self.assertTrue(result.ok)
        self.assertEqual(seen, ["corrected"])

    def test_partial_failure_remains_pending_and_retries(self):
        for target in ("parent_1", "parent_2"):
            self.outbox.enqueue(
                idempotency_key=f"daily:2026-08-15:{target}",
                target=target,
                payload="briefing",
                kind="daily",
            )

        result = self.outbox.deliver_pending(lambda target, _: target == "parent_1")
        self.assertEqual((result.sent, result.failed), (1, 1))
        self.assertEqual(self.outbox.counts(), {"pending": 1, "sending": 0, "sent": 1, "expired": 0})

        self.now += timedelta(seconds=60)
        retried = self.outbox.deliver_pending(lambda _target, _payload: True)
        self.assertEqual(retried.sent, 1)
        self.assertEqual(self.outbox.counts()["pending"], 0)

    def test_expired_message_is_never_sent(self):
        self.outbox.enqueue(
            idempotency_key="expired",
            target="parent_1",
            payload="old briefing",
            kind="daily",
            expires_at=self.now - timedelta(seconds=1),
        )
        sender = mock.Mock(return_value=True)
        result = self.outbox.deliver_pending(sender)
        self.assertEqual(result.expired, 1)
        sender.assert_not_called()

    def test_active_lease_prevents_duplicate_delivery(self):
        self.outbox.enqueue(
            idempotency_key="one-copy",
            target="parent_1",
            payload="briefing",
            kind="daily",
        )
        competing = DeliveryOutbox(self.db_path, clock=lambda: self.now)
        competing_sender = mock.Mock(return_value=True)

        def first_sender(_target, _payload):
            competing_result = competing.deliver_pending(competing_sender)
            self.assertEqual(competing_result.sent, 0)
            return True

        result = self.outbox.deliver_pending(first_sender)
        self.assertEqual(result.sent, 1)
        competing_sender.assert_not_called()


class AtomicStateTests(unittest.TestCase):
    def test_atomic_json_replaces_complete_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            atomic_write_json(path, {"ok": True, "items": [1, 2, 3]})
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["items"], [1, 2, 3])


class EmailProcessingLedgerTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        self.db_path = handle.name
        self.now = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
        self.ledger = EmailProcessingLedger(self.db_path, clock=lambda: self.now)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_failed_email_remains_retryable(self):
        self.ledger.begin("42", "Ukeplan uke 34")
        self.ledger.update("42", "email-logged")
        self.ledger.fail("42", "ukeplan", "could not determine week")
        self.assertEqual(self.ledger.status("42"), "failed")
        self.assertFalse(self.ledger.is_terminal("42"))

        self.ledger.begin("42", "Ukeplan uke 34")
        self.assertEqual(self.ledger.status("42"), "processing")
        self.ledger.complete("42")
        self.assertTrue(self.ledger.is_terminal("42"))

    def test_quarantine_is_terminal_and_auditable(self):
        self.ledger.begin("99", "Unknown sender")
        self.ledger.complete("99", quarantined=True)
        self.assertEqual(self.ledger.status("99"), "quarantined")
        self.assertTrue(self.ledger.is_terminal("99"))


if __name__ == "__main__":
    unittest.main()
