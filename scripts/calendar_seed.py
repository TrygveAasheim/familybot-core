#!/usr/bin/env python3
"""Seed national holidays and configured local school calendars.

Public holidays are calculated rather than frozen to one installation's years.
School dates are household-owned configuration because municipalities and
individual schools publish different calendars.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from family_config import load_family_config
from reliability import database_path


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def setup_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS norwegian_holidays (
            date TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS school_calendar (
            id INTEGER PRIMARY KEY,
            year_label TEXT NOT NULL,
            event_type TEXT NOT NULL,
            name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            applies_to TEXT NOT NULL DEFAULT 'all',
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS school_years (
            year_label TEXT PRIMARY KEY,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            notes TEXT
        );
        """
    )


def seed_public_holidays(connection: sqlite3.Connection, years: range) -> int:
    holidays: list[tuple[date, str]] = []
    for year in years:
        easter = easter_sunday(year)
        holidays.extend(
            [
                (date(year, 1, 1), "Nyttårsdag"),
                (easter - timedelta(days=3), "Skjærtorsdag"),
                (easter - timedelta(days=2), "Langfredag"),
                (easter, "Første påskedag"),
                (easter + timedelta(days=1), "Andre påskedag"),
                (date(year, 5, 1), "Arbeidernes dag"),
                (date(year, 5, 17), "Grunnlovsdagen"),
                (easter + timedelta(days=39), "Kristi himmelfartsdag"),
                (easter + timedelta(days=49), "Første pinsedag"),
                (easter + timedelta(days=50), "Andre pinsedag"),
                (date(year, 12, 25), "Første juledag"),
                (date(year, 12, 26), "Andre juledag"),
            ]
        )
    connection.executemany(
        """INSERT INTO norwegian_holidays(date,name,kind)
           VALUES(?,?,'public_holiday')
           ON CONFLICT(date) DO UPDATE SET name=excluded.name,kind=excluded.kind""",
        [(day.isoformat(), name) for day, name in holidays],
    )
    return len(holidays)


def configured_school() -> tuple[str, list[dict[str, object]]]:
    value = load_family_config().get("school", {})
    if not isinstance(value, dict):
        return "all", []
    municipality = str(value.get("municipality") or "all").strip()
    events = value.get("calendar_events", [])
    return municipality, [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def seed_school_calendar(
    connection: sqlite3.Connection,
    municipality: str,
    events: list[dict[str, object]],
) -> int:
    # One installation has one authoritative local school calendar. Clear only
    # school-owned rows, including the historical hard-coded Oslo seed, while
    # retaining calculated national holidays.
    connection.execute("DELETE FROM norwegian_holidays WHERE kind='school_break'")
    connection.execute("DELETE FROM school_calendar")
    connection.execute("DELETE FROM school_years")
    school_years: dict[str, dict[str, str]] = {}
    for event in events:
        year_label = str(event["year_label"])
        event_type = str(event["event_type"])
        name = str(event["name"])
        start = str(event["start_date"])
        end = str(event.get("end_date") or start)
        notes = str(event.get("notes") or "") or None
        connection.execute(
            """INSERT INTO school_calendar(
                   year_label,event_type,name,start_date,end_date,applies_to,notes
               ) VALUES(?,?,?,?,?,?,?)""",
            (year_label, event_type, name, start, end, municipality, notes),
        )
        if event_type == "break":
            for day in date_range(date.fromisoformat(start), date.fromisoformat(end)):
                if day.isoweekday() <= 5:
                    connection.execute(
                        """INSERT OR IGNORE INTO norwegian_holidays(date,name,kind)
                           VALUES(?,?,'school_break')""",
                        (day.isoformat(), name),
                    )
        school_year = school_years.setdefault(year_label, {})
        if event_type == "first_day":
            school_year["start"] = start
        elif event_type == "last_day":
            school_year["end"] = end
    for year_label, boundaries in school_years.items():
        if "start" not in boundaries or "end" not in boundaries:
            continue
        connection.execute(
            """INSERT INTO school_years(year_label,start_date,end_date,notes)
               VALUES(?,?,?,?)
               ON CONFLICT(year_label) DO UPDATE SET
                   start_date=excluded.start_date,end_date=excluded.end_date,notes=excluded.notes""",
            (
                year_label,
                boundaries["start"],
                boundaries["end"],
                f"Konfigurert skolerute for {municipality}",
            ),
        )
    return len(events)


def is_school_day(check_date: date, connection: sqlite3.Connection) -> tuple[bool, str]:
    if check_date.isoweekday() > 5:
        return False, "weekend"
    row = connection.execute(
        "SELECT name,kind FROM norwegian_holidays WHERE date=?", (check_date.isoformat(),)
    ).fetchone()
    return (False, f"{row[1]}: {row[0]}") if row else (True, "school day")


def main() -> int:
    current_year = date.today().year
    municipality, events = configured_school()
    with sqlite3.connect(database_path()) as connection:
        setup_schema(connection)
        holiday_count = seed_public_holidays(
            connection, range(current_year - 1, current_year + 4)
        )
        school_count = seed_school_calendar(connection, municipality, events)
    print(
        f"Calendar ready: {holiday_count} national holidays calculated; "
        f"{school_count} configured school events for {municipality}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
