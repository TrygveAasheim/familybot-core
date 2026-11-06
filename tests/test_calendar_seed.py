from __future__ import annotations

import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from calendar_seed import (  # noqa: E402
    easter_sunday,
    seed_public_holidays,
    seed_school_calendar,
    setup_schema,
)


class CalendarSeedTests(unittest.TestCase):
    def test_easter_and_national_holidays_are_calculated_for_new_years(self):
        self.assertEqual(date(2030, 4, 21), easter_sunday(2030))
        with sqlite3.connect(":memory:") as connection:
            setup_schema(connection)
            count = seed_public_holidays(connection, range(2029, 2031))
            self.assertEqual(24, count)
            self.assertEqual(
                "Andre påskedag",
                connection.execute(
                    "SELECT name FROM norwegian_holidays WHERE date='2030-04-22'"
                ).fetchone()[0],
            )

    def test_fictional_municipality_calendar_is_idempotent_and_updatable(self):
        events = [
            {
                "year_label": "2027-2028",
                "event_type": "first_day",
                "name": "Første skoledag",
                "start_date": "2027-08-16",
                "end_date": "2027-08-16",
            },
            {
                "year_label": "2027-2028",
                "event_type": "break",
                "name": "Høstferie",
                "start_date": "2027-10-04",
                "end_date": "2027-10-08",
            },
            {
                "year_label": "2027-2028",
                "event_type": "last_day",
                "name": "Siste skoledag",
                "start_date": "2028-06-16",
                "end_date": "2028-06-16",
            },
        ]
        with sqlite3.connect(":memory:") as connection:
            setup_schema(connection)
            connection.execute(
                "INSERT INTO school_calendar(year_label,event_type,name,start_date,end_date,applies_to) "
                "VALUES('2025-2026','break','Gammel Oslo-ferie','2026-02-16','2026-02-20','oslo')"
            )
            connection.execute(
                "INSERT INTO school_years(year_label,start_date,end_date) "
                "VALUES('2025-2026','2025-08-18','2026-06-19')"
            )
            connection.execute(
                "INSERT INTO norwegian_holidays(date,name,kind) "
                "VALUES('2026-02-16','Gammel Oslo-ferie','school_break')"
            )
            connection.execute(
                "INSERT INTO norwegian_holidays(date,name,kind) "
                "VALUES('2027-05-17','Grunnlovsdagen','public_holiday')"
            )
            seed_school_calendar(connection, "Nordvik kommune (fiktiv)", events)
            events[1]["end_date"] = "2027-10-11"
            seed_school_calendar(connection, "Nordvik kommune (fiktiv)", events)
            self.assertEqual(
                3, connection.execute("SELECT COUNT(*) FROM school_calendar").fetchone()[0]
            )
            self.assertEqual(
                "2027-10-11",
                connection.execute(
                    "SELECT end_date FROM school_calendar WHERE event_type='break'"
                ).fetchone()[0],
            )
            self.assertEqual(
                ("2027-08-16", "2028-06-16"),
                connection.execute(
                    "SELECT start_date,end_date FROM school_years WHERE year_label='2027-2028'"
                ).fetchone(),
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM school_calendar WHERE applies_to='oslo'"
                ).fetchone()
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM school_years WHERE year_label='2025-2026'"
                ).fetchone()
            )
            self.assertEqual(
                "public_holiday",
                connection.execute(
                    "SELECT kind FROM norwegian_holidays WHERE date='2027-05-17'"
                ).fetchone()[0],
            )


if __name__ == "__main__":
    unittest.main()
