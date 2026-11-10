import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stack_security_audit as audit


class StackAuditTests(unittest.TestCase):
    def test_config_rejects_public_permissions_relative_paths_and_unknown_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            valid = {"schema_version": 1, "workspace": directory, "binaries": {"openclaw": "/test/openclaw"}}
            path.write_text(json.dumps(valid))
            path.chmod(0o644)
            with self.assertRaises(audit.CheckError):
                audit.load_config(path)
            path.chmod(0o600)
            self.assertEqual(audit.load_config(path), valid)
            for update in ({"workspace": "relative"}, {"workspace": "/"},
                           {"binaries": {"shell": "/bin/sh"}}, {"auto_update": True}):
                path.write_text(json.dumps({**valid, **update}))
                with self.assertRaises(audit.CheckError):
                    audit.load_config(path)

    def test_missing_tool_and_registry_failure_are_unavailable_not_clean(self):
        with mock.patch.object(audit, "command", side_effect=audit.CheckError("secret path")):
            result = audit.audit({"binaries": {"codex": "/missing"}})
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("secret", json.dumps(result))
        with mock.patch.object(audit, "command", return_value=(0, "codex-cli 0.162.0", "")), \
                mock.patch.object(audit, "fetch", side_effect=audit.CheckError("offline")):
            result = audit.audit({"binaries": {"codex": "/fake"}})
        self.assertEqual(result["checks"]["release_codex"]["status"], "unavailable")

    def test_latest_is_information_and_never_an_upgrade(self):
        with mock.patch.object(audit, "command", return_value=(0, "codex-cli 0.162.0", "")) as run, \
                mock.patch.object(audit, "fetch", return_value={"version": "0.167.0"}):
            result = audit.audit({"binaries": {"codex": "/test/codex"}})
        self.assertTrue(result["versions"]["codex"]["update_available"])
        self.assertEqual(result["status"], "ok")
        run.assert_called_once_with(["/test/codex", "--version"])

    def test_security_report_keeps_only_counts(self):
        payload = {"summary": {"critical": 1, "warn": 2, "info": 1},
                   "findings": [{"details": "PRIVATE CREDENTIAL"}]}
        with mock.patch.object(audit, "command", side_effect=[(0, "2026.11.2", ""), (0, json.dumps(payload), "")]), \
                mock.patch.object(audit, "fetch", return_value={"version": "2026.11.2"}):
            result = audit.audit({"binaries": {"openclaw": "/test/openclaw"}})
        self.assertEqual(result["status"], "attention")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["checks"]["openclaw_security"]["critical"], 1)

    def test_audit_error_cannot_be_reported_as_zero_vulnerabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "package-lock.json").write_text("{}")
            payload = {"error": {"message": "PRIVATE"}, "metadata": {"vulnerabilities": {
                key: 0 for key in ("info", "low", "moderate", "high", "critical", "total")}}}
            with mock.patch.object(audit, "command", side_effect=[(0, "10.9.8", ""), (1, json.dumps(payload), "")]):
                result = audit.audit({"binaries": {"npm": "/test/npm"}, "portal_repo": directory})
            self.assertEqual(result["status"], "unavailable")
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_save_is_atomic_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory/stack-security-audit.json"
            audit.save_report(directory, {"status": "ok"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with mock.patch.object(audit.os, "replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    audit.save_report(directory, {"status": "unavailable"})
            self.assertEqual(json.loads(path.read_text()), {"status": "ok"})
            self.assertEqual(list(path.parent.glob(".stack-audit-*")), [])

    def test_timeout_does_not_print_command_or_stderr(self):
        with mock.patch.object(audit.subprocess, "run", side_effect=subprocess.TimeoutExpired("PRIVATE", 90)):
            with self.assertRaisesRegex(audit.CheckError, "command_unavailable_or_timeout"):
                audit.command(["/fake"])

    def test_no_configured_checks_is_not_a_clean_scan(self):
        self.assertEqual(audit.audit({})["status"], "unavailable")

    def test_schedule_is_opt_in_weekly_no_shell_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.plist"
            audit.write_schedule(path, Path(directory) / "config.json", directory)
            data = plistlib.loads(path.read_bytes())
            self.assertEqual(data["StartCalendarInterval"], {"Weekday": 0, "Hour": 12, "Minute": 15})
            self.assertFalse(data["RunAtLoad"])
            self.assertEqual(data["ProgramArguments"][2], "--config")
            self.assertNotIn("sh", data["ProgramArguments"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                audit.write_schedule(path, Path(directory) / "other.json", directory)

    def test_fetch_rejects_non_allowlisted_urls_before_network(self):
        with mock.patch.object(audit.urllib.request, "urlopen") as fetch:
            for value in ("file:///tmp/secret", "http://nodejs.org/dist/index.json", "https://example.org"):
                with self.assertRaises(audit.CheckError):
                    audit.fetch(value)
            fetch.assert_not_called()

    def test_same_major_node_update_does_not_recommend_a_breaking_major(self):
        with mock.patch.object(audit, "command", return_value=(0, "v22.23.2", "")), \
                mock.patch.object(audit, "fetch", return_value=[
                    {"version": "v26.13.0"}, {"version": "v22.23.4"}, {"version": "v22.23.3"}]):
            result = audit.audit({"binaries": {"portal_node": "/test/node"}})
        self.assertEqual(result["versions"]["portal_node"]["latest_same_major"], "22.23.4")

    def test_python_advisory_and_partial_scan_are_not_clean(self):
        for payload, code, expected in (
            ({"dependencies": [{"name": "fictional", "vulns": [{"id": "CVE-fixture"}]}]}, 1, "attention"),
            ({"dependencies": [{"name": "fictional", "skip_reason": "not found"}]}, 0, "unavailable"),
            ({"dependencies": []}, 0, "unavailable"),
        ):
            results = [(0, "Python 3.12.13", ""), (0, "pip-audit 2.10.0", ""),
                       (0, json.dumps({"sqlite": "3.50.4", "openssl": "OpenSSL 3.5.6"}), ""),
                       (0, "/fictional/site-packages", ""), (code, json.dumps(payload), "")]
            with self.subTest(expected=expected), \
                    mock.patch.object(audit, "command", side_effect=results), \
                    mock.patch.object(audit, "fetch", return_value=[
                        {"name": "Python 3.12.16", "is_published": True, "pre_release": False}]):
                result = audit.audit({"binaries": {"core_python": "/python", "pip_audit": "/audit"}})
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["versions"]["core_python"]["latest_same_minor"], "3.12.16")


if __name__ == "__main__":
    unittest.main()
