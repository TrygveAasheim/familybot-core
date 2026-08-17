import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from validate_config import validate


ROOT = Path(__file__).resolve().parent.parent


class ValidateConfigTests(unittest.TestCase):
    def load_fixture(self):
        return json.loads((ROOT / "tests/fixtures/family.test.json").read_text(encoding="utf-8"))

    def validate_value(self, value, mode=0o600):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "family.local.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            path.chmod(mode)
            return validate(path)

    def test_valid_full_configuration_passes(self):
        report = self.validate_value(self.load_fixture())
        self.assertEqual(report.errors, [])

    def test_shipped_template_is_structurally_valid(self):
        report = validate(ROOT / "config/family.example.json", allow_placeholders=True, check_permissions=False)
        self.assertEqual(report.errors, [])

    def test_placeholders_duplicate_ids_and_open_permissions_fail(self):
        value = self.load_fixture()
        value["members"][0]["name"] = "PARENT_1_NAME"
        value["members"][1]["member_id"] = value["members"][0]["member_id"]
        report = self.validate_value(value, mode=0o644)
        combined = "\n".join(report.errors)
        self.assertIn("placeholder", combined)
        self.assertIn("unique", combined)
        self.assertIn("permissions", combined)

    def test_bad_origin_and_partial_cabin_fail(self):
        value = copy.deepcopy(self.load_fixture())
        value["portal"]["allowed_origins"] = ["https://evil.example:3000"]
        value["integrations"]["weather"]["cabin_label"] = "Cabin"
        report = self.validate_value(value)
        combined = "\n".join(report.errors)
        self.assertIn("exact http origin", combined)
        self.assertIn("supplied together", combined)

    def test_secret_fields_are_rejected_without_printing_values(self):
        value = self.load_fixture()
        value["integrations"]["email"]["api_token"] = "do-not-print-this"
        report = self.validate_value(value)
        combined = "\n".join(report.errors)
        self.assertIn("credential-like fields", combined)
        self.assertNotIn("do-not-print-this", combined)

    def test_transport_requires_supported_mode_and_direction_quay(self):
        value = self.load_fixture()
        value["integrations"]["transport"]["transport_mode"] = "spaceship"
        value["integrations"]["transport"].pop("direction_quay_id")
        report = self.validate_value(value)
        combined = "\n".join(report.errors)
        self.assertIn("metro, bus, tram, rail, or water", combined)
        self.assertIn("direction_quay_id", combined)


if __name__ == "__main__":
    unittest.main()
