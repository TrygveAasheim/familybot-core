import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ["FAMILYBOT_FAMILY_CONFIG"] = str(Path(__file__).parent / "fixtures/family.test.json")

import briefing
import email_routing
import parse_ukeplan
import process_emails
from reliability import DeliveryOutbox


class SubjectTests(unittest.TestCase):
    def test_explicit_valid_period_and_invalid_metadata(self):
        self.assertEqual(process_emails.subject_period("Ukeplan uke 43 Child Two 6A", 2026), (43, 2026))
        self.assertEqual(process_emails.subject_period("Ukeplan uke 1/2027", 2026), (1, 2027))
        self.assertEqual(process_emails.subject_period("Ukeplan Child Two", 2026), (None, 2026))
        for subject in ("Uke 54", "Uke 100", "Uke 0", "Uke 53/2025", "Uke 42 og uke 43"):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                process_emails.subject_period(subject, 2026)

    def test_subject_controls_dates_despite_old_pdf_header(self):
        page = mock.Mock()
        page.extract_text.return_value = "Ukeplan for 6A uke 35\n24. august\nLes hver dag."
        page.extract_words.return_value = []
        pdf = mock.MagicMock()
        pdf.__enter__.return_value.pages = [page]
        with mock.patch.object(parse_ukeplan.pdfplumber, "open", return_value=pdf):
            data = parse_ukeplan.parse_ukeplan_pdf("test.pdf", 4, 2026, week_override=43)
            unchanged = parse_ukeplan.parse_ukeplan_pdf("test.pdf", 4, 2026)
        self.assertEqual(data["week"], 43)
        self.assertEqual(list(data["days"]), [f"2026-10-{day}" for day in range(19, 24)])
        self.assertEqual(unchanged["week"], 35)
        self.assertIn("uke 35", data["raw_text"])

    def test_parent_subject_wins_over_forwarded_sender_and_body(self):
        connection = mock.MagicMock()
        with mock.patch.object(email_routing, "_get_db", return_value=connection), \
             mock.patch.object(email_routing, "_do_resolve") as fallback:
            result = email_routing.resolve_sender(
                "test", "Ukeplan Child Two 6A uke 43", "parent@example.invalid", "Parent",
                "From: Teacher <teacher@school.invalid>\nUkeplan Child One 3A uke 35",
            )
        self.assertEqual(result.member_id, 4)
        fallback.assert_not_called()

    def test_non_parent_subject_does_not_override_sender(self):
        connection = mock.MagicMock()
        expected = email_routing.RoutingResult(3, "Child One", "school", "exact", None, "rule", False)
        with mock.patch.object(email_routing, "_get_db", return_value=connection), \
             mock.patch.object(email_routing, "_do_resolve", return_value=expected):
            result = email_routing.resolve_sender("test", "Child Two 6A", "teacher@school.invalid", "Teacher", "")
        self.assertEqual(result.member_id, 3)

    def test_storage_keeps_old_week_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "test.db")
            with sqlite3.connect(db) as c:
                c.executescript("""
                    CREATE TABLE family_members (id INTEGER, teacher TEXT);
                    CREATE TABLE week_plans (id INTEGER PRIMARY KEY, member_id INTEGER, week_number INTEGER,
                        year INTEGER, raw_text TEXT, summary TEXT, source_email_id TEXT, teacher TEXT,
                        layout_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE week_plan_days (week_plan_id INTEGER, day TEXT, date TEXT, note TEXT, homework TEXT, bring TEXT);
                    INSERT INTO week_plans (member_id,week_number,year,raw_text,source_email_id) VALUES (4,35,2026,'old content','1');
                """)
            parsed = {"week":43, "raw_text":"PDF content only", "days":{"2026-10-19":{"weekday":"mandag"}}}
            with mock.patch.object(process_emails,"DB_PATH",db), \
                 mock.patch.object(process_emails,"parse_ukeplan_pdf",return_value=parsed) as parser:
                for _ in range(2):
                    self.assertTrue(process_emails.save_ukeplan_attachments(["test.pdf"],4,"2",subject="Uke 43",year=2026))
                self.assertEqual(parser.call_args.kwargs["week_override"],43)
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute("SELECT week_number,raw_text FROM week_plans ORDER BY week_number").fetchall(),
                                 [(35,"old content"),(43,"PDF content only")])
                self.assertEqual(c.execute("SELECT count(*) FROM week_plan_days").fetchone()[0],1)


class CompleteBriefingTests(unittest.TestCase):
    def test_fallback_preserves_names_full_text_and_late_sections(self):
        content = "En fullstendig setning. " * 100 + "SLUTTEN."
        data = {"today":{"events":[{"title":f"event {i}"} for i in range(20)]},
                "ukeplaner":{"child_1":{"summary":"cut off", "raw_text":content},
                             "child_2":{"summary":"Andre barns beskjed."}}}
        for render in (briefing.render_daily_fallback, briefing.render_weekly_fallback):
            text = render(data)
            self.assertIn("Ukeplan Child One:",text)
            self.assertIn("Ukeplan Child Two:",text)
            self.assertIn(content,text)
            self.assertNotIn("Child_1",text)

    def test_all_model_text_payloads_are_kept(self):
        completed = mock.Mock(returncode=0, stdout=json.dumps({"result":{"payloads":[{"text":"First."},{"text":"Last."}]}}))
        with mock.patch.object(briefing.subprocess,"run",return_value=completed):
            self.assertEqual(briefing.generate_text("test"),"First.\n\nLast.")

    def test_model_failure_still_delivers_complete_named_fallback(self):
        content = "Viktig beskjed. " * 100 + "Avslutning."
        data = {"ukeplaner":{"child_1":{"raw_text":content}}}
        with mock.patch.object(briefing,"collect_daily",return_value=data), \
             mock.patch.object(briefing,"record_briefing"), \
             mock.patch.object(briefing,"generate_text",return_value=""), \
             mock.patch.object(briefing,"deliver_briefing",return_value=True) as deliver:
            self.assertTrue(briefing.run_daily())
        self.assertIn("Child One",deliver.call_args.args[1])
        self.assertIn(content,deliver.call_args.args[1])

    def test_both_recipients_have_all_parts_before_first_send(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory)/"test.db"
            text = "Full melding. " * 400
            parts = briefing.message_parts(text)
            counts = []
            def sender(target, message):
                with sqlite3.connect(db) as c:
                    counts.append(c.execute("SELECT COUNT(*) FROM delivery_outbox").fetchone()[0])
                return True
            with mock.patch.object(briefing,"database_path",return_value=db), \
                 mock.patch.object(briefing,"vacation_mode_active",return_value=False), \
                 mock.patch.object(briefing,"send_telegram",side_effect=sender):
                self.assertTrue(briefing.deliver_briefing("daily",text))
                self.assertTrue(briefing.deliver_briefing("daily",text+" extra"*900))
            self.assertEqual(counts,[2*len(parts)]*(2*len(parts)))

    def test_split_is_lossless_and_safe_for_unicode(self):
        text = "Hei! 🥳 " * 1700
        parts = briefing.message_parts(text)
        self.assertEqual("".join(parts),text)
        self.assertTrue(all(len(p.encode("utf-16-le")) // 2 < 4000 for p in parts))

    def test_parts_are_frozen_and_only_failed_recipient_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026,10,20,tzinfo=timezone.utc)
            outbox = DeliveryOutbox(Path(directory)/"test.db",clock=lambda:now)
            for target in ("one","two"):
                outbox.enqueue_parts(idempotency_key=target,target=target,parts=["First.","Last."],kind="test")
            result = outbox.deliver_pending(lambda target,text: target=="one")
            self.assertEqual((result.sent,result.failed),(2,2))
            outbox.enqueue_parts(idempotency_key="two",target="two",parts=["Changed.","Different.","Extra."],kind="test")
            now += timedelta(hours=2)
            sent = []
            outbox.deliver_pending(lambda target,text: sent.append((target,text)) or True)
            self.assertEqual(sent,[("two","First."),("two","Last.")])


if __name__ == "__main__":
    unittest.main()
