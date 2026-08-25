import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import interpret_ukeplan


class UkeplanInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [{"id": "page2-block1", "text": "Les side 10 til torsdag."}]

    def test_validation_requires_source_backed_weekday_items(self):
        payload = {
            "days": [{
                "date": "2026-08-20",
                "items": [{
                    "category": "homework",
                    "text": "Les side 10 til torsdag.",
                    "source_blocks": ["page2-block1"],
                    "confidence": 0.96,
                }],
            }],
            "general_notes": [],
        }
        result = interpret_ukeplan.validate_interpretation(
            payload, year=2026, week=34, blocks=self.blocks
        )
        self.assertEqual(result["days"][0]["weekday"], "torsdag")
        self.assertEqual(result["days"][0]["items"][0]["category"], "homework")

    def test_validation_rejects_invented_text_and_wrong_date(self):
        payload = {
            "days": [{
                "date": "2026-08-22",
                "items": [{
                    "category": "event",
                    "text": "Invented appointment",
                    "source_blocks": ["page2-block1"],
                    "confidence": 1,
                }],
            }],
            "general_notes": [],
        }
        with self.assertRaises(ValueError):
            interpret_ukeplan.validate_interpretation(
                payload, year=2026, week=34, blocks=self.blocks
            )

    def test_validation_tolerates_pdf_line_break_variation(self):
        payload = {
            "days": [{
                "date": "2026-08-20",
                "items": [{
                    "category": "homework",
                    "text": "Les side 10 til torsdag",
                    "source_blocks": ["page2-block1"],
                    "confidence": 0.8,
                }],
            }],
            "general_notes": [],
        }
        result = interpret_ukeplan.validate_interpretation(
            payload, year=2026, week=34, blocks=self.blocks
        )
        self.assertEqual(result["days"][0]["items"][0]["source_blocks"], ["page2-block1"])

    def test_fenced_json_is_parsed(self):
        self.assertEqual(
            interpret_ukeplan.parse_model_json('```json\n{"days": []}\n```'),
            {"days": []},
        )

    def test_pdf_prompt_uses_original_document_as_primary_input(self):
        prompt = interpret_ukeplan.prompt_for_plan(
            2026, 34, {}, "/private/ukeplan.pdf"
        )
        self.assertIn("/private/ukeplan.pdf", prompt)
        self.assertIn("days is an array, never an object", prompt)
        self.assertIn("PDF is the only source of truth", prompt)
        self.assertIn("weekly_tasks", prompt)
        self.assertIn("general_info", prompt)

    def test_validation_normalizes_structured_week_buckets(self):
        payload = {
            "days": [],
            "weekly_tasks": [{
                "text": "Les side 10 til torsdag.",
                "source_blocks": ["page2-block1"],
            }],
            "general_info": [],
        }
        result = interpret_ukeplan.validate_interpretation(
            payload, year=2026, week=34, blocks=self.blocks
        )
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["weekly_tasks"][0]["text"], "Les side 10 til torsdag.")
        self.assertEqual(result["general_info"], [])

    def test_model_failure_is_durable_and_does_not_remove_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "family.db"
            layout = {"version": 1, "source_blocks": self.blocks, "layout_text": ""}
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """CREATE TABLE week_plans(
                       id INTEGER PRIMARY KEY, week_number INTEGER, year INTEGER,
                       layout_json TEXT, created_at TEXT)"""
                )
                connection.execute(
                    "INSERT INTO week_plans(id,week_number,year,layout_json,created_at) VALUES(1,34,2026,?,?)",
                    (json.dumps(layout), "2026-08-17T08:00:00+02:00"),
                )
            with mock.patch.object(interpret_ukeplan, "database_path", return_value=db_path), \
                    mock.patch.object(interpret_ukeplan, "invoke_model", side_effect=RuntimeError("offline")):
                self.assertEqual(interpret_ukeplan.run(limit=1), 0)
            with sqlite3.connect(db_path) as connection:
                status, plan_count = connection.execute(
                    "SELECT status,(SELECT count(*) FROM week_plans) FROM week_plan_interpretations"
                ).fetchone()
            self.assertEqual(status, "failed")
            self.assertEqual(plan_count, 1)


if __name__ == "__main__":
    unittest.main()
