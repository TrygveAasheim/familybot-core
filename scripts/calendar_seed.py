#!/usr/bin/env python3
"""
Seeds the Norwegian calendar foundation into the family database.

Layer 1: Norwegian public holidays (røde dager) 2025-2027
Layer 2: Oslo skolerute 2025-2026 (school breaks, first/last day)
Layer 3: School year metadata and grade advancement logic

Sources: Standard Norwegian holiday rules + Oslo kommune skolerute.
Week numbers follow ISO 8601 (Monday = day 1), which matches Norwegian standard.
"""

import sqlite3
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from reliability import database_path

DB_PATH = str(database_path())


def date_range(start: date, end: date):
    """Yield each date from start to end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def conn():
    return sqlite3.connect(DB_PATH)


def setup_schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS norwegian_holidays (
        date TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL  -- 'public_holiday' | 'school_break' | 'school_event'
    );

    CREATE TABLE IF NOT EXISTS school_calendar (
        id INTEGER PRIMARY KEY,
        year_label TEXT NOT NULL,       -- '2025-2026'
        event_type TEXT NOT NULL,       -- 'first_day' | 'last_day' | 'break' | 'planning_day'
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,         -- same as start_date for single days
        applies_to TEXT DEFAULT 'all',  -- 'all' | 'oslo'
        notes TEXT
    );
    """)


def seed_public_holidays(c):
    """
    Norwegian public holidays (røde dager).
    Fixed dates are straightforward. Easter-based dates calculated per year.
    """

    # Easter Sundays (pre-calculated)
    easter = {
        2025: date(2025, 4, 20),
        2026: date(2026, 4, 5),
        2027: date(2027, 3, 28),
    }

    holidays = []

    for year, easter_sunday in easter.items():
        e = easter_sunday
        holidays += [
            # Easter week
            (e - timedelta(days=3), "Skjærtorsdag"),
            (e - timedelta(days=2), "Langfredag"),
            (e,                     "Første påskedag"),
            (e + timedelta(days=1), "Andre påskedag"),
            # Ascension (39 days after Easter)
            (e + timedelta(days=39), "Kristi himmelfartsdag"),
            # Pentecost (49 and 50 days after Easter)
            (e + timedelta(days=49), "Første pinsedag"),
            (e + timedelta(days=50), "Andre pinsedag"),
            # Fixed dates
            (date(year, 1, 1),  "Nyttårsdag"),
            (date(year, 5, 1),  "Arbeidernes dag"),
            (date(year, 5, 17), "Grunnlovsdagen"),
            (date(year, 12, 25), "Første juledag"),
            (date(year, 12, 26), "Andre juledag"),
        ]

    for d, name in holidays:
        c.execute("""
            INSERT OR REPLACE INTO norwegian_holidays (date, name, kind)
            VALUES (?, ?, 'public_holiday')
        """, (d.isoformat(), name))

    print(f"  Seeded {len(holidays)} public holidays (2025-2027)")


def seed_oslo_skolerute(c):
    """
    Oslo kommune skolerute 2025-2026.
    Source: Oslo kommune published school calendar.
    """

    events = [
        # School year boundaries
        ("2025-2026", "first_day",    "Første skoledag",       "2025-08-18", "2025-08-18"),
        ("2025-2026", "last_day",     "Siste skoledag",        "2026-06-19", "2026-06-19"),

        # Autumn break (høstferie) — week 40
        ("2025-2026", "break",        "Høstferie",             "2025-09-29", "2025-10-03"),

        # Christmas break (juleferie)
        ("2025-2026", "break",        "Juleferie",             "2025-12-22", "2026-01-02"),

        # Winter break (vinterferie) — week 8
        ("2025-2026", "break",        "Vinterferie",           "2026-02-16", "2026-02-20"),

        # Easter break (påskeferie) — week 13/14
        # Easter 2026 = April 5. Schools typically closed Mon-Fri of that week + day before
        ("2025-2026", "break",        "Påskeferie",            "2026-03-30", "2026-04-10"),

        # Planning days (no school for pupils)
        ("2025-2026", "planning_day", "Planleggingsdag",       "2025-08-14", "2025-08-15"),
        ("2025-2026", "planning_day", "Planleggingsdag",       "2026-01-02", "2026-01-02"),

        # Next school year boundary (for grade advancement logic)
        ("2026-2027", "first_day",    "Første skoledag",       "2026-08-17", "2026-08-17"),
        ("2026-2027", "last_day",     "Siste skoledag",        "2027-06-18", "2027-06-18"),
        ("2026-2027", "break",        "Høstferie",             "2026-09-28", "2026-10-02"),
        ("2026-2027", "break",        "Juleferie",             "2026-12-21", "2027-01-01"),
        ("2026-2027", "break",        "Vinterferie",           "2027-02-15", "2027-02-19"),
        ("2026-2027", "break",        "Påskeferie",            "2027-03-22", "2027-04-02"),
    ]

    for year_label, event_type, name, start, end in events:
        c.execute("""
            INSERT OR REPLACE INTO school_calendar
                (year_label, event_type, name, start_date, end_date, applies_to)
            VALUES (?, ?, ?, ?, ?, 'oslo')
        """, (year_label, event_type, name, start, end))

        # Also write school breaks as individual holiday entries
        if event_type == "break":
            start_d = date.fromisoformat(start)
            end_d = date.fromisoformat(end)
            for d in date_range(start_d, end_d):
                if d.isoweekday() <= 5:  # Mon-Fri only
                    c.execute("""
                        INSERT OR IGNORE INTO norwegian_holidays (date, name, kind)
                        VALUES (?, ?, 'school_break')
                    """, (d.isoformat(), name))

    print(f"  Seeded {len(events)} skolerute events (Oslo, 2025-2027)")


def seed_school_years(c):
    """Update school_years table with correct data."""
    years = [
        ("2025-2026", "2025-08-18", "2026-06-19",
         "Norsk skoleår. Barnas trinn hentes fra lokal familiekonfig."),
        ("2026-2027", "2026-08-17", "2027-06-18",
         "Norsk skoleår. Barnas trinn hentes fra lokal familiekonfig."),
    ]
    for label, start, end, notes in years:
        c.execute("""
            INSERT OR REPLACE INTO school_years (year_label, start_date, end_date, notes)
            VALUES (?, ?, ?, ?)
        """, (label, start, end, notes))
    print(f"  Seeded {len(years)} school years")


def is_school_day(check_date: date, db_conn) -> tuple[bool, str]:
    """
    Returns (is_school_day, reason).
    A day is NOT a school day if it's a weekend, public holiday, or school break.
    """
    c = db_conn.cursor()

    # Weekend
    if check_date.isoweekday() > 5:
        return False, "weekend"

    # Public holiday or school break
    row = c.execute("""
        SELECT name, kind FROM norwegian_holidays WHERE date = ?
    """, (check_date.isoformat(),)).fetchone()

    if row:
        return False, f"{row[1]}: {row[0]}"

    return True, "school day"


if __name__ == "__main__":
    db = conn()
    c = db.cursor()

    print("Setting up calendar foundation...")
    setup_schema(c)
    seed_public_holidays(c)
    seed_oslo_skolerute(c)
    seed_school_years(c)
    db.commit()

    # Verification
    print("\nSpot checks:")
    test_dates = [
        date(2026, 4, 19),  # Today (Sunday)
        date(2026, 4, 20),  # Monday, normal week
        date(2026, 4, 6),   # Easter Monday
        date(2026, 5, 1),   # Arbeidernes dag
        date(2026, 5, 17),  # Grunnlovsdagen
        date(2026, 2, 17),  # Vinterferie
        date(2026, 4, 28),  # Normal school day
    ]
    for d in test_dates:
        school, reason = is_school_day(d, db)
        iso_week = d.isocalendar().week
        day_name = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"][d.isoweekday()-1]
        status = "SKOLEDAG" if school else f"IKKE skole ({reason})"
        print(f"  {day_name} {d.isoformat()} uke {iso_week:02d}: {status}")

    db.close()
    print("\nKalenderfundament klar.")
