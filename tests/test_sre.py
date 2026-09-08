import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sre import JOB_BY_LABEL, LaunchdInfo, latest_calendar_due, next_calendar_due  # noqa: E402
from sre_reconcile import plan_actions  # noqa: E402


class ScheduleContractTests(unittest.TestCase):
    def test_weekend_next_run_is_schedule_aware(self):
        tuesday = datetime(2026, 9, 8, 4, 30, tzinfo=timezone.utc)
        spec = JOB_BY_LABEL["familybot.briefing.weekend"]
        latest = latest_calendar_due(spec, tuesday)
        following = next_calendar_due(spec, tuesday)
        self.assertEqual(latest.weekday(), 6)  # Sunday, in UTC for this date
        self.assertEqual(following.weekday(), 5)  # Saturday, in UTC for this date

    def test_overdue_interval_job_is_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "Library" / "LaunchAgents").mkdir(parents=True)
            plist = home / "Library" / "LaunchAgents" / "familybot.delivery.plist"
            plist.write_text("<plist/>", encoding="utf-8")
            plist.chmod(0o600)
            current = datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc)
            state = {
                "status": "success",
                "finished_at": (current - timedelta(minutes=20)).isoformat(),
                "last_exit_code": 0,
            }
            actions = plan_actions(
                home=home,
                launchd={"familybot.delivery": LaunchdInfo(True, False, None, 10, 0)},
                states={"familybot.delivery": state},
                current=current,
                previous={"actions": {}, "failures": {}},
            )
            self.assertEqual([action["kind"] for action in actions], ["kickstart"])
            self.assertTrue(any("familybot.delivery" in argument for argument in actions[0]["argv"]))

    def test_calendar_briefing_failure_is_never_auto_replayed(self):
        current = datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc)
        actions = plan_actions(
            home=Path(tempfile.gettempdir()),
            launchd={"familybot.briefing.weekend": LaunchdInfo(True, False, None, 2, 2)},
            states={
                "familybot.briefing.weekend": {
                    "status": "failed",
                    "finished_at": (current - timedelta(hours=1)).isoformat(),
                    "last_exit_code": 2,
                }
            },
            current=current,
            previous={"actions": {}, "failures": {}},
        )
        self.assertEqual(actions, [])

    def test_gateway_restart_requires_two_failures(self):
        actions = plan_actions(
            home=Path(tempfile.gettempdir()),
            launchd={},
            states={},
            current=datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc),
            previous={"actions": {}, "failures": {}},
            gateway_failures=1,
        )
        self.assertFalse(any(action["kind"] == "gateway_restart" for action in actions))


if __name__ == "__main__":
    unittest.main()
