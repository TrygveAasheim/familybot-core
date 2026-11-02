import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from configure_openclaw_model import apply_configuration, audit


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
