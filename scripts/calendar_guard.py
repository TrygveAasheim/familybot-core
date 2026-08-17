#!/usr/bin/env python3
"""
calendar_guard.py — Temporal validation layer for all calendar_events writes.

Rules:
1. WEEK ALIGNMENT: Events parsed from a week plan must fall within that week's
   Monday–Friday. Events outside the stated week number are rejected unless
   they are explicitly future references (e.g. "Uke 18: ..." in a uke 17 plan).

2. NO PAST EVENTS: Events in the past (before today) are never written for
   recurring activities or school-week content. Exception: Spond events with
   explicit future dates are written as-is.

3. WEEK NUMBER CROSS-CHECK: Given a week_number and year, compute the actual
   Monday–Friday date range and verify any date claimed to belong to that week.

4. DUPLICATE GUARD: Before insert, verify UNIQUE constraint will not fire.
   (The DB has a UNIQUE constraint on member_id+title+event_date+source+source_ref,
   so INSERT OR IGNORE is always safe — but we log when we skip.)

Usage:
    from calendar_guard import validate_event, safe_insert_event

    result = validate_event(
        title="Kick off bokuken",
        event_date=date(2026, 4, 28),
        stated_week=17,
        year=2026,
        source="email",
        allow_past=False,
    )
    if result.ok:
        safe_insert_event(conn, ...)
    else:
        print(f"Rejected: {result.reason}")
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import zoneinfo

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    warning: str = ""  # non-fatal notes


def week_date_range(week: int, year: int) -> tuple[date, date]:
    """Return (monday, friday) for ISO week number in given year."""
    # ISO week: Monday = day 1
    jan4 = date(year, 1, 4)  # Jan 4 is always in week 1
    monday_w1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = monday_w1 + timedelta(weeks=week - 1)
    friday = monday + timedelta(days=4)
    return monday, friday


def validate_event(
    title: str,
    event_date: date,
    stated_week: Optional[int] = None,
    year: int = 2026,
    source: str = "email",
    allow_past: bool = False,
    future_week_ref: bool = False,  # True if event is from a "Uke N+1:" section
) -> ValidationResult:
    """
    Validate a calendar event before DB insertion.

    Returns ValidationResult with ok=True if safe to insert.
    """
    today = date.today()

    # Rule 1: No past events (unless explicitly allowed)
    if not allow_past and event_date < today:
        return ValidationResult(
            ok=False,
            reason=f"Event '{title}' on {event_date} is in the past (today={today}). Skipped."
        )

    # Rule 2: Week alignment check
    if stated_week is not None and not future_week_ref:
        monday, friday = week_date_range(stated_week, year)
        # Allow Saturday/Sunday too (some events may be weekend)
        sunday = monday + timedelta(days=6)
        if not (monday <= event_date <= sunday):
            # Check which week the event_date actually belongs to
            actual_week = event_date.isocalendar().week
            actual_year = event_date.isocalendar().year
            return ValidationResult(
                ok=False,
                reason=(
                    f"Event '{title}' on {event_date} (ISO week {actual_week}/{actual_year}) "
                    f"does not belong to stated week {stated_week}/{year} "
                    f"({monday} – {friday}). "
                    f"If this is a future reference, set future_week_ref=True."
                )
            )

    # Rule 3: Sanity check — event not more than 1 year in the future
    if event_date > today + timedelta(days=366):
        return ValidationResult(
            ok=False,
            reason=f"Event '{title}' on {event_date} is more than 1 year in the future. Suspicious."
        )

    return ValidationResult(ok=True)


def validate_week_events(
    events: list[dict],
    stated_week: int,
    year: int,
    source: str = "email",
) -> tuple[list[dict], list[dict]]:
    """
    Filter a list of event dicts (each with 'title' and 'event_date' as date obj).
    Returns (accepted, rejected) lists.
    Each rejected item has an added 'reject_reason' key.
    """
    today = date.today()
    monday, friday = week_date_range(stated_week, year)

    accepted = []
    rejected = []

    for ev in events:
        title = ev.get("title", "?")
        event_date = ev.get("event_date")
        future_week_ref = ev.get("future_week_ref", False)

        if not isinstance(event_date, date):
            ev["reject_reason"] = f"event_date is not a date object: {event_date!r}"
            rejected.append(ev)
            continue

        result = validate_event(
            title=title,
            event_date=event_date,
            stated_week=stated_week,
            year=year,
            source=source,
            allow_past=False,
            future_week_ref=future_week_ref,
        )

        if result.ok:
            accepted.append(ev)
        else:
            ev["reject_reason"] = result.reason
            rejected.append(ev)

    return accepted, rejected


def safe_insert_event(
    conn: sqlite3.Connection,
    member_id: Optional[int],
    title: str,
    event_date: date,
    location: Optional[str] = None,
    description: Optional[str] = None,
    bring: Optional[str] = None,
    requires_response: int = 0,
    source: str = "email",
    source_ref: Optional[str] = None,
    week_number: Optional[int] = None,
    year: Optional[int] = None,
) -> bool:
    """
    Insert a calendar event safely. Returns True if inserted, False if skipped (duplicate).
    Always uses INSERT OR IGNORE — never creates duplicates.
    """
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO calendar_events
            (member_id, title, event_date, location, description, bring,
             requires_response, source, source_ref, week_number, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        member_id, title, event_date.isoformat(), location, description, bring,
        requires_response, source, source_ref, week_number, year
    ))
    inserted = c.rowcount > 0
    conn.commit()
    if not inserted:
        print(f"  [SKIP duplicate] {title} on {event_date}")
    return inserted


def purge_past_email_events(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """
    Remove calendar_events from 'email' source that are now in the past.
    Spond events are left alone (managed by spond_sync).
    Returns list of removed titles.
    """
    today = date.today()
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, title, event_date FROM calendar_events
        WHERE source='email' AND event_date < ?
    """, (today.isoformat(),)).fetchall()

    removed = []
    for row_id, title, event_date in rows:
        removed.append(f"{title} ({event_date})")
        if not dry_run:
            c.execute("DELETE FROM calendar_events WHERE id=?", (row_id,))

    if not dry_run and removed:
        conn.commit()

    return removed


if __name__ == "__main__":
    # Self-test
    print("Testing week_date_range:")
    mon, fri = week_date_range(17, 2026)
    print(f"  Week 17/2026: {mon} – {fri}")
    mon, fri = week_date_range(18, 2026)
    print(f"  Week 18/2026: {mon} – {fri}")

    print("\nTesting validate_event:")
    # Should pass — uke 18, mandag 27. april
    r = validate_event("Bursdag Laura", date(2026, 4, 29), stated_week=18, year=2026)
    print(f"  Bursdag 29.apr in week 18: ok={r.ok} {r.reason}")

    # Should fail — uke 17 men dato er 28. april (uke 18)
    r = validate_event("Kick off bokuken", date(2026, 4, 28), stated_week=17, year=2026)
    print(f"  Kick off 28.apr in week 17: ok={r.ok} reason={r.reason}")

    # Should pass as future_week_ref
    r = validate_event("DKS Rådhuset", date(2026, 4, 29), stated_week=17, year=2026, future_week_ref=True)
    print(f"  DKS 29.apr in week 17 (future_week_ref): ok={r.ok}")
