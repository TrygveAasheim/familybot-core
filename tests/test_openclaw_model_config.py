import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from configure_openclaw_model import (
    ConfigurationError,
    OpenClawClient,
    apply_configuration,
    audit,
    audit_codex_runtime,
)


class FakeClient:
    def __init__(self):
        self.default = "openai/gpt-5.5"
        self.jobs = [
            {
                "id": "retired-job",
                "name": "Email ingestion",
                "payload": {"kind": "agentTurn", "model": "openai/gpt-5.5"},
            },
            {
                "id": "custom-job",
                "name": "Intentional custom model",
                "payload": {"kind": "agentTurn", "model": "openai/gpt-6-astra"},
            },
            {
                "id": "inherited-job",
                "name": "Inherited model",
                "payload": {"kind": "agentTurn"},
            },
        ]
        self.calls = []

    def model_config(self):
        return {"primary": self.default}

    def cron_jobs(self):
        return self.jobs

    def set_default_model(self, model):
        self.calls.append(("set", model))
        self.default = model

    def clear_job_model(self, job_id):
        self.calls.append(("clear", job_id))
        for job in self.jobs:
            if job["id"] == job_id:
                job["payload"].pop("model", None)

    def restart_gateway(self):
        self.calls.append(("restart",))


class OpenClawModelConfigTests(unittest.TestCase):
    def test_absent_plugins_section_is_optional_but_other_errors_are_not(self):
        client = OpenClawClient("openclaw")
        with mock.patch.object(client, "_json", side_effect=ConfigurationError(
            "OpenClaw command failed: Config path not found: plugins. Run openclaw config validate"
        )):
            self.assertEqual(client.plugin_config(), {})
        with mock.patch.object(client, "_json", side_effect=ConfigurationError("permission denied")):
            with self.assertRaises(ConfigurationError):
                client.plugin_config()

    def test_malformed_plugin_shapes_fail_safely(self):
        for value in (None, {"entries": []}, {"entries": {"codex": []}},
                      {"entries": {"codex": {"enabled": True, "config": []}}},
                      {"entries": {"codex": {"enabled": True, "config": {"appServer": []}}}}):
            with self.subTest(value=value):
                self.assertTrue(audit_codex_runtime(value))

    def test_missing_codex_executable_is_detected_without_model_call(self):
        plugins = {"entries": {"codex": {"enabled": True, "config": {
            "appServer": {"command": "/missing/private-path/codex"}}}}}
        with mock.patch("configure_openclaw_model.shutil.which", return_value=None):
            issues = audit_codex_runtime(plugins)
        self.assertEqual(len(issues), 1)
        self.assertNotIn("private-path", issues[0])
        self.assertIn("missing or not executable", issues[0])

    def test_available_codex_and_remote_or_disabled_plugins(self):
        with mock.patch("configure_openclaw_model.shutil.which", return_value="/test/codex"):
            self.assertEqual(audit_codex_runtime({"entries": {"codex": {"enabled": True,
                "config": {"appServer": {"command": "/test/codex"}}}}}), [])
        with mock.patch("configure_openclaw_model.shutil.which") as probe:
            self.assertEqual(audit_codex_runtime({}), [])
            self.assertEqual(audit_codex_runtime({"entries": {"codex": {"enabled": True}}}), [])
            self.assertEqual(audit_codex_runtime({"entries": {"codex": {"enabled": False}}}), [])
            self.assertEqual(audit_codex_runtime({"entries": {"codex": {"enabled": True,
                "config": {"appServer": {"transport": "websocket"}}}}}), [])
            probe.assert_not_called()

    def test_audit_detects_default_drift_and_retired_cron_pin(self):
        client = FakeClient()
        issues = audit(
            client.model_config(),
            client.cron_jobs(),
            "openai/gpt-5.6-sol",
            {"openai/gpt-5.5"},
        )
        self.assertEqual(len(issues), 2)
        self.assertIn("agents.defaults.model", issues[0])
        self.assertIn("Email ingestion", issues[1])

    def test_apply_repairs_retired_values_and_preserves_custom_override(self):
        client = FakeClient()
        changed, cleared, issues = apply_configuration(
            client,
            "openai/gpt-5.6-sol",
            {"openai/gpt-5.5"},
            restart=True,
        )
        self.assertTrue(changed)
        self.assertEqual(cleared, ["Email ingestion"])
        self.assertEqual(issues, [])
        self.assertEqual(
            client.calls,
            [
                ("set", "openai/gpt-5.6-sol"),
                ("clear", "retired-job"),
                ("restart",),
            ],
        )
        custom = next(job for job in client.jobs if job["id"] == "custom-job")
        self.assertEqual(custom["payload"]["model"], "openai/gpt-6-astra")

    def test_compliant_configuration_is_a_noop(self):
        client = FakeClient()
        client.default = "openai/gpt-5.6-sol"
        client.jobs[0]["payload"].pop("model")
        changed, cleared, issues = apply_configuration(
            client,
            "openai/gpt-5.6-sol",
            {"openai/gpt-5.5"},
            restart=True,
        )
        self.assertFalse(changed)
        self.assertEqual(cleared, [])
        self.assertEqual(issues, [])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
