import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_launchd import EXPECTED, validate_launchctl_output, validate_templates  # noqa: E402


class LaunchdScheduleTests(unittest.TestCase):
    def test_source_templates_match_the_weekday_contract(self):
        errors = validate_templates(ROOT / "ops" / "launchd")
        self.assertEqual(errors, [])

    def test_weekend_and_weekday_do_not_overlap(self):
        weekday = set(EXPECTED["familybot.briefing.weekday.plist.example"]["calendar"])
        weekend = set(EXPECTED["familybot.briefing.weekend.plist.example"]["calendar"])
        self.assertEqual({day for day, _, _ in weekday}, {1, 2, 3, 4, 5})
        self.assertEqual({day for day, _, _ in weekend}, {0, 6})
        self.assertTrue(weekday.isdisjoint(weekend))

    def test_loaded_launchctl_output_is_checked_against_the_contract(self):
        output = """
        descriptor = {
            "Minute" => 45
            "Hour" => 6
            "Weekday" => 1
        }
        descriptor = {
            "Minute" => 0
            "Hour" => 8
            "Weekday" => 6
        }
        """
        self.assertEqual(validate_launchctl_output("familybot.briefing.weekday", output), [
            "familybot.briefing.weekday: loaded calendar intervals are [(1, 6, 45), (6, 8, 0)], expected [(1, 6, 45), (2, 6, 45), (3, 6, 45), (4, 6, 45), (5, 6, 45)]"
        ])
        self.assertEqual(validate_launchctl_output("familybot.briefing.weekend", output), [
            "familybot.briefing.weekend: loaded calendar intervals are [(1, 6, 45), (6, 8, 0)], expected [(0, 8, 0), (6, 8, 0)]"
        ])


if __name__ == "__main__":
    unittest.main()
