import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import briefing
import interpret_ukeplan
import outcome_health
import process_emails
import sre_reconcile


class OutcomeTests(unittest.TestCase):
    def test_conflicting_attribution_rejected_before_model_call(self):
        layout = json.dumps({"attribution": {"year": 2026, "week": 35}})
        with mock.patch.object(interpret_ukeplan, "invoke_model") as invoke, \
                mock.patch.object(interpret_ukeplan, "mark_failed") as failed:
            self.assertFalse(interpret_ukeplan.interpret_one(Path("unused.db"), (1, 43, 2026, layout, 1)))
            invoke.assert_not_called()
            failed.assert_called_once()

    def test_missing_model_executable_falls_back(self):
        with mock.patch.object(briefing.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(briefing.generate_text("fixture"), "")

    def test_daily_fallback_preserves_auxiliary_sections(self):
        data = {"weather": {"evening_note": "Kald kveld"},
                "cabin_weather": ["Sol på hytta"],
                "upcoming": [{"date": "I morgen", "events": [{"title": "Skolefest"}],
                              "recurring": [{"activity": "Fotball"}]}]}
        text = briefing.render_daily_fallback(data)
        for required in ("Kald kveld", "Sol på hytta", "Skolefest", "Fotball"):
            self.assertIn(required, text)

    def test_message_validation_and_complete_fallback(self):
        data = {"ukeplaner": {"child_1": {"raw_text": "Les boka."}},
                "kanban": {"parent_1": [{"priority": "must-do", "title": "Bestill time"}]},
                "pending_rsvp": [{"title": "Klassetur", "member": "Child One"}]}
        for text in ("", "child_1 Les boka.", "Child One Les boka.",
                     "Bestill time Klassetur"):
            self.assertFalse(briefing.valid_briefing(text, data))
        for render in (briefing.render_daily_fallback, briefing.render_weekly_fallback):
            text = render(data)
            self.assertTrue(briefing.valid_briefing(text, data))
            self.assertIn("Les boka.", text)

    def test_telemetry_failure_does_not_block_fallback(self):
        with mock.patch.object(briefing, "record_briefing", side_effect=OSError):
            self.assertEqual(briefing.select_briefing("daily", "", {}, lambda _: "Complete."), "Complete.")

    def test_private_quality_record_recovery_and_staleness(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"FAMILYBOT_WORKSPACE": directory}):
            self.assertEqual(outcome_health.briefing_health()["status"], "ok")
            outcome_health.record_briefing("daily", True)
            path = Path(directory) / "memory/briefing-outcome-daily.json"
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertEqual(set(json.loads(path.read_text())), {"checked_at", "fallback"})
            self.assertEqual(outcome_health.briefing_health()["status"], "warn")
            outcome_health.record_briefing("daily", False)
            self.assertEqual(outcome_health.briefing_health()["status"], "ok")
            with mock.patch.object(outcome_health, "datetime") as clock:
                clock.now.return_value = datetime.now(timezone.utc) - timedelta(days=10)
                outcome_health.record_briefing("daily", True)
            self.assertEqual(outcome_health.briefing_health()["status"], "ok")

    def test_current_failed_plan_warns_historical_failure_does_not(self):
        with sqlite3.connect(":memory:") as connection:
            connection.executescript("""
                CREATE TABLE week_plans(id INTEGER, year INTEGER, week_number INTEGER, layout_json TEXT);
                CREATE TABLE week_plan_interpretations(week_plan_id INTEGER, status TEXT, updated_at TEXT);
                INSERT INTO week_plans VALUES(1,2026,43,'{}');
                INSERT INTO week_plan_interpretations VALUES(1,'failed',NULL);
            """)
            self.assertEqual(outcome_health.interpretation_health(connection, date(2026,10,20))["status"], "warn")
            self.assertEqual(outcome_health.interpretation_health(connection, date(2026,11,20))["status"], "ok")
            connection.execute("UPDATE week_plan_interpretations SET status='accepted'")
            self.assertEqual(outcome_health.interpretation_health(connection, date(2026,10,20))["status"], "ok")

    def test_pending_grace_period_and_malformed_timestamp(self):
        with sqlite3.connect(":memory:") as connection:
            connection.executescript("""
                CREATE TABLE week_plans(id INTEGER, year INTEGER, week_number INTEGER, layout_json TEXT);
                CREATE TABLE week_plan_interpretations(week_plan_id INTEGER, status TEXT, updated_at TEXT);
                INSERT INTO week_plans VALUES(1,2026,43,'{}');
            """)
            for updated, expected in ((datetime.now(timezone.utc).isoformat(), "ok"),
                                      ((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(), "warn"),
                                      ("invalid", "warn")):
                connection.execute("DELETE FROM week_plan_interpretations")
                connection.execute("INSERT INTO week_plan_interpretations VALUES(1,'pending',?)", (updated,))
                self.assertEqual(outcome_health.interpretation_health(connection, date(2026,10,20))["status"], expected)

    def test_sre_deduplicates_quality_alert_until_recovery(self):
        state = {}
        now = datetime.now(timezone.utc)
        for i in range(1, 5):
            status = {"checked_at": str(i), "results": [
                {"service": "briefing_quality", "status": "warn", "msg": "fallback"}]}
            _, alerts = sre_reconcile.update_health_failures(status, state, now)
            if i == 3:
                self.assertEqual(len(alerts), 1)
                state["health_failures"]["briefing_quality"]["alerted"] = True
            else:
                self.assertEqual(alerts, [])
        sre_reconcile.update_health_failures({"checked_at": "5", "results": [
            {"service": "briefing_quality", "status": "ok", "msg": "recovered"}]}, state, now)
        self.assertEqual(state["health_failures"]["briefing_quality"]["count"], 0)

    def test_bad_parsed_period_never_opens_database(self):
        for parsed in ({"week": 35}, {"week": 43, "days": {"2026-08-24": {}}}):
            with mock.patch.object(process_emails, "parse_ukeplan_pdf", return_value=parsed), \
                    mock.patch.object(process_emails, "get_db") as connect:
                with self.assertRaises(ValueError):
                    process_emails.save_ukeplan("fixture.pdf", 4, "2", year=2026, subject="Uke 43")
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
