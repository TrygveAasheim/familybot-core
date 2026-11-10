import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import outcome_health
import sre_reconcile


class BriefingAlertRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = mock.patch.dict(os.environ, {"FAMILYBOT_WORKSPACE": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.now = datetime.now(timezone.utc)
        self.state = {}

    def poll(self, index):
        return sre_reconcile.update_health_failures(
            {"checked_at": str(index), "results": [outcome_health.briefing_health()]},
            self.state, self.now,
        )

    def test_one_fallback_is_not_three_failures_after_repeated_polls(self):
        outcome_health.record_briefing("weekly", True)
        for i in range(10):
            counters, alerts = self.poll(i)
            self.assertEqual(alerts, [])
            self.assertEqual(counters["briefing_quality"], 1)

    def test_distinct_failed_generations_escalate_once_then_recover(self):
        for i in range(1, 4):
            outcome_health.record_briefing("daily", True)
            counters, alerts = self.poll(i)
            self.assertEqual(counters["briefing_quality"], i)
            self.assertEqual(len(alerts), int(i == 3))
            if alerts:
                self.assertEqual(alerts[0]["unit"], "consecutive fallback briefings")
        self.state["health_failures"]["briefing_quality"]["alerted"] = True
        self.assertEqual(self.poll(4)[1], [])
        outcome_health.record_briefing("daily", False)
        self.assertEqual(self.poll(5)[0]["briefing_quality"], 0)
        outcome_health.record_briefing("daily", True)
        self.assertEqual(self.poll(6)[0]["briefing_quality"], 1)

    def test_legacy_counter_does_not_inherit_inflated_poll_count(self):
        path = Path(self.directory.name) / "memory/briefing-outcome-weekly.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"checked_at": self.now.isoformat(), "fallback": True}))
        self.state["health_failures"] = {"briefing_quality": {
            "count": 99, "event_key": "old", "alerted": True,
        }}
        self.assertEqual(self.poll(1)[0]["briefing_quality"], 1)
        self.assertEqual(self.poll(2)[1], [])

    def test_daily_success_does_not_erase_separate_weekly_failure(self):
        outcome_health.record_briefing("weekly", True)
        outcome_health.record_briefing("daily", False)
        self.assertEqual(outcome_health.briefing_health()["status"], "warn")
        self.assertEqual(self.poll(1)[0]["briefing_quality"], 1)

    def test_recovery_between_health_polls_starts_a_new_alertable_incident(self):
        for _ in range(3):
            outcome_health.record_briefing("daily", True)
        self.assertEqual(len(self.poll(1)[1]), 1)
        self.state["health_failures"]["briefing_quality"]["alerted"] = True
        outcome_health.record_briefing("daily", False)
        for _ in range(3):
            outcome_health.record_briefing("daily", True)
        self.assertEqual(len(self.poll(2)[1]), 1)

    def test_stale_failure_does_not_extend_new_streak(self):
        with mock.patch.object(outcome_health, "datetime") as clock:
            clock.now.return_value = self.now - timedelta(days=10)
            outcome_health.record_briefing("daily", True)
        outcome_health.record_briefing("daily", True)
        self.assertEqual(self.poll(1)[0]["briefing_quality"], 1)

    def test_disabled_kind_does_not_contribute_to_health(self):
        outcome_health.record_briefing("weekly", True)
        self.assertEqual(outcome_health.briefing_health(["daily"])["status"], "ok")

    def test_bad_records_warn_without_crashing_or_leaking(self):
        path = Path(self.directory.name) / "memory/briefing-outcome-daily.json"
        path.parent.mkdir()
        for value in ([], {"checked_at": "bad", "fallback": True},
                      {"checked_at": (self.now + timedelta(days=1)).isoformat(), "fallback": True},
                      {"checked_at": self.now.isoformat(), "fallback": "secret"},
                      {"checked_at": self.now.isoformat(), "fallback": True, "consecutive_fallbacks": -2}):
            path.write_text(json.dumps(value))
            result = outcome_health.briefing_health()
            self.assertEqual(result["status"], "warn")
            self.assertEqual(result["msg"], "Outcome record unreadable")
            self.assertNotIn("secret", str(result))

    def test_reason_allowlist_and_kind_validation(self):
        outcome_health.record_briefing("daily", True, "secret payload")
        self.assertEqual(outcome_health.briefing_health()["observations"][0]["reason"], "unknown")
        with self.assertRaises(ValueError):
            outcome_health.record_briefing("../outside", True)


if __name__ == "__main__":
    unittest.main()
