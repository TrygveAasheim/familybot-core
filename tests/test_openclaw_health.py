import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sre_reconcile  # noqa: E402
from openclaw_health import check_openclaw, gateway_health, telegram_health  # noqa: E402
from sre_reconcile import (  # noqa: E402
    gateway_recovery_count,
    plan_actions,
    record_action_attempt,
    update_health_failures,
)


class OpenClawHealthTests(unittest.TestCase):
    def test_gateway_uses_rpc_not_changed_prose(self):
        for kind in ["read", "connectivity", "future-kind"]:
            data = {"rpc": {"ok": True, "kind": kind}, "service": {"runtime": {"status": "running"}}}
            self.assertEqual(gateway_health(0, json.dumps(data))["status"], "ok")

    def test_gateway_unknown_timeout_and_cli_errors_are_not_restartable(self):
        for code, output in [(0, '{}'), (0, '[]'), (0, 'null'), (0, 'not json'),
                             (-1, ''), (1, '{"rpc":{"ok":true}}'),
                             (0, '{"rpc":{"ok":"true"}}'),
                             (0, '{"rpc":true}'),
                             (0, 'Runtime: running\nConnectivity check: ok')]:
            with self.subTest(code=code, output=output):
                result = gateway_health(code, output)
                self.assertEqual(result["status"], "warn")
                self.assertNotIn("auto_fix", result)

    def test_gateway_failed_probe_requires_stopped_service_for_recovery(self):
        for service, restart in [({}, False), ({"loaded": True}, False),
                                 ({"runtime": {"status": "running"}}, False),
                                 ({"loaded": False}, False),
                                 ({"loaded": False, "targetRole": "diagnostic-only"}, False),
                                 ({"loaded": False, "targetRole": "target"}, True),
                                 ({"runtime": {"status": "stopped"}, "targetRole": "target"}, True)]:
            result = gateway_health(1, json.dumps({"rpc": {"ok": False}, "service": service}))
            self.assertEqual(result["status"], "critical")
            self.assertEqual(result.get("auto_fix") == "restart", restart)

    def account(self, **overrides):
        return {"enabled": True, "configured": True, "running": True,
                "connected": True, "lastError": None, "probe": {"ok": True}, **overrides}

    def test_telegram_checks_enabled_accounts_and_legacy_summary(self):
        for data in [
            {"channels": {"telegram": self.account()}},
            {"channelAccounts": {"telegram": [self.account(), {"enabled": False}]}},
            {"channels": {"telegram": self.account(connected=None)}},
        ]:
            self.assertEqual(telegram_health(0, json.dumps(data))["status"], "ok")

    def test_telegram_heartbeat_or_top_level_ok_is_not_channel_evidence(self):
        for output in ['Last heartbeat | ok-token | telegram', '{"ok":true}', 'null', '[]',
                       '{"channels":{"telegram":true}}',
                       '{"channelAccounts":{"telegram":{}}}',
                       '{"channelAccounts":{"telegram":[null]}}']:
            self.assertEqual(telegram_health(0, output)["status"], "warn")

    def test_telegram_failures_and_unknown_fields_do_not_pass(self):
        for override in [{"configured": False}, {"running": False}, {"connected": False},
                         {"probe": None}, {"probe": {"ok": False}}, {"probe": {"ok": "true"}},
                         {"lastError": "PRIVATE_ERROR"}, {"enabled": False}]:
            data = {"channelAccounts": {"telegram": [self.account(), self.account(**override)]}}
            # Explicitly disabled accounts do not make enabled ones unhealthy.
            expected = "ok" if override == {"enabled": False} else "warn"
            result = telegram_health(0, json.dumps(data))
            self.assertEqual(result["status"], expected)
            self.assertNotIn("PRIVATE_ERROR", json.dumps(result))
        for accounts in [[], [{"enabled": False}]]:
            self.assertEqual(telegram_health(0, json.dumps({"channelAccounts": {"telegram": accounts}}))["status"], "warn")
        self.assertEqual(telegram_health(1, json.dumps({"channels": {"telegram": self.account()}}))["status"], "warn")

    def test_probe_commands_are_bounded_json_and_never_send_messages(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return -1, "PRIVATE_OUTPUT", "PRIVATE_ERROR"

        results = check_openclaw("/test/openclaw", run)
        self.assertEqual(calls, [
            ["/test/openclaw", "gateway", "status", "--json", "--timeout", "8000"],
            ["/test/openclaw", "channels", "status", "--probe", "--json", "--timeout", "8000"],
        ])
        self.assertTrue(all(r["status"] == "warn" for r in results))
        self.assertNotIn("PRIVATE", json.dumps(results))


class GatewayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.current = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
        self.previous = {}

    def status(self, current=None, **overrides):
        return {"checked_at": (current or self.current).isoformat(), "results": [{
            "service": "gateway", "status": "critical", "auto_fix": "restart",
            "recovery_evidence": "service_stopped", **overrides}]}

    def actions(self, count=2):
        return plan_actions(home=Path("/fictional"), launchd={}, states={}, current=self.current,
                            previous=self.previous, gateway_failures=count, job_specs=())

    def test_distinct_fresh_failures_then_recovery(self):
        status = self.status()
        self.assertEqual(gateway_recovery_count(status, self.previous, self.current), 1)
        self.assertEqual(gateway_recovery_count(status, self.previous, self.current), 1)
        later = self.current + timedelta(minutes=30)
        self.assertEqual(gateway_recovery_count(self.status(later), self.previous, later), 2)
        self.assertEqual(gateway_recovery_count(self.status(later, status="ok"), self.previous, later), 0)

    def test_unknown_legacy_auth_or_stale_failure_never_restarts(self):
        for status in [self.status(recovery_evidence=None), self.status(auto_fix=None),
                       self.status(status="warn"), self.status(self.current - timedelta(minutes=11)),
                       self.status(self.current + timedelta(seconds=1)), {"results": []}]:
            self.previous = {"failures": {"gateway": {"key": "service_stopped", "count": 9}}}
            self.assertEqual(gateway_recovery_count(status, self.previous, self.current), 0)

    def test_restart_cooldown_matches_persisted_key_and_applies_to_failed_attempt(self):
        self.assertEqual(self.actions(1), [])
        action = self.actions()[0]
        record_action_attempt(self.previous, action, self.current)
        self.assertIn("gateway_restart:openclaw.gateway", self.previous["actions"])
        self.assertEqual(self.actions(), [])
        self.current += timedelta(minutes=15)
        self.assertEqual(len(self.actions()), 1)
        self.previous = {"actions": {"gateway:restart": self.current.isoformat()}}
        self.assertEqual(self.actions(), [])

    def test_real_success_clears_alert_counters_without_manual_reset(self):
        self.previous = {"health_failures": {name: {"count": 7, "alerted": True}
                                            for name in ["gateway", "telegram"]}}
        status = {"checked_at": self.current.isoformat(), "results": [
            gateway_health(0, '{"rpc":{"ok":true}}'),
            telegram_health(0, '{"channels":{"telegram":{"configured":true,"running":true,"probe":{"ok":true}}}}'),
        ]}
        counters, alerts = update_health_failures(status, self.previous, self.current)
        self.assertEqual([counters[k] for k in ["gateway", "telegram"]], [0, 0])
        self.assertEqual(alerts, [])

    def test_failed_restart_attempt_is_persisted_and_not_repeated(self):
        for outcome in [subprocess.CompletedProcess([], 1, '', 'failed'),
                        subprocess.TimeoutExpired('openclaw', 30)]:
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                db = workspace / 'db'
                db.mkdir()
                (db / 'health_status.json').write_text(json.dumps(self.status()))
                (db / 'sre_state.json').write_text(json.dumps({'failures': {'gateway': {
                    'count': 1, 'key': 'service_stopped', 'checked_at': 'previous-observation'}}}))
                with (patch.object(sre_reconcile, 'workspace_path', return_value=workspace),
                      patch.object(sre_reconcile, 'now', return_value=self.current),
                      patch.object(sre_reconcile, 'active_job_specs', return_value=()),
                      patch.object(sys, 'argv', ['sre_reconcile.py']),
                      patch.object(sre_reconcile, 'send_health_alert') as send,
                      patch.object(sre_reconcile.subprocess, 'run') as run):
                    if isinstance(outcome, Exception):
                        run.side_effect = outcome
                    else:
                        run.return_value = outcome
                    self.assertEqual(sre_reconcile.main(), 0)
                    self.assertEqual(sre_reconcile.main(), 0)
                    self.assertEqual(run.call_count, 1)
                    send.assert_not_called()
                saved = json.loads((db / 'sre_state.json').read_text())
                self.assertIn('gateway_restart:openclaw.gateway', saved['actions'])
                self.assertEqual((db / 'sre_state.json').stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
