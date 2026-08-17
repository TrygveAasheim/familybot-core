#!/usr/bin/env python3
"""
Spond monitor for FamilyBot.
Fetches events, checks RSVP status, detects new/changed items,
stores in SQLite, and returns items needing attention.
"""

import asyncio
import os
import sys
import sqlite3
import json
from datetime import datetime, timezone, timedelta
import zoneinfo
import types

sys.path.insert(0, os.path.dirname(__file__))
from reliability import atomic_write_json, connect_db, database_path, workspace_path
from family_config import integration

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
DB_PATH = str(database_path())
SECRETS = str(workspace_path() / "secrets.env")
STATE_PATH = workspace_path() / "db" / "spond_sync_state.json"

# Group identifiers are household data and therefore exist only in local config.
SPOND_GROUPS = {
    str(group["group_id"]): (str(group.get("name") or "Spond-gruppe"), group.get("member_id"))
    for group in integration("spond").get("groups", []) if group.get("group_id")
}


def load_secrets():
    with open(SECRETS) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip()


def get_db():
    return connect_db(DB_PATH)


def ensure_schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS spond_events (
        id TEXT PRIMARY KEY,
        group_id TEXT,
        group_name TEXT,
        member_id INTEGER,
        title TEXT,
        event_date TEXT,
        event_end TEXT,
        location TEXT,
        description TEXT,
        rsvp_accepted INTEGER DEFAULT 0,
        rsvp_declined INTEGER DEFAULT 0,
        rsvp_unanswered INTEGER DEFAULT 0,
        my_rsvp TEXT,              -- 'accepted' | 'declined' | 'pending' | 'unknown'
        rsvp_deadline TEXT,
        requires_response INTEGER DEFAULT 0,
        raw_json TEXT,
        first_seen TEXT DEFAULT (datetime('now')),
        last_updated TEXT DEFAULT (datetime('now')),
        notified INTEGER DEFAULT 0  -- 1 once we've alerted about this event
    );

    CREATE TABLE IF NOT EXISTS spond_messages (
        id TEXT PRIMARY KEY,
        group_id TEXT,
        group_name TEXT,
        member_id INTEGER,
        sender_name TEXT,
        text TEXT,
        sent_at TEXT,
        first_seen TEXT DEFAULT (datetime('now')),
        notified INTEGER DEFAULT 0
    );
    """)


async def login_auth2(client):
    """Compatibility login for spond<1.2.1 on the Mac's system Python."""
    url = f"{client.api_url}auth2/login"
    payload = {"email": client.username, "password": client.password}
    async with client.clientsession.post(url, json=payload) as response:
        data = await response.json(content_type=None)
        access = data.get("accessToken") if isinstance(data, dict) else None
        token = access.get("token") if isinstance(access, dict) else None
        if response.status >= 400 or not token:
            safe_error = {k: data.get(k) for k in ("error", "errorKey", "errorCode", "message")
                          if isinstance(data, dict) and data.get(k)}
            raise RuntimeError(f"Spond login failed ({response.status}): {safe_error or 'no diagnostic'}")
        client.token = token


async def fetch_all(s, group_id, group_name, member_id, conn):
    c = conn.cursor()
    now = datetime.now(timezone.utc)
    # Look 6 months back and 12 months forward
    min_start = now - timedelta(days=180)
    max_end = now + timedelta(days=365)

    new_events = []
    changed_events = []

    try:
        events = await s.get_events(
            group_id=group_id,
            min_start=min_start,
            max_end=max_end,
            max_events=50
        )
    except Exception as e:
        print(f"  Error fetching events for {group_name}: {e}")
        return [], [], str(e)

    for e in events:
        eid = e.get("id", "")
        title = e.get("heading", "")
        start = e.get("startTimestamp", "")[:10] if e.get("startTimestamp") else ""
        end = e.get("endTimestamp", "")[:10] if e.get("endTimestamp") else ""
        location = (e.get("location") or {}).get("feature", "") or ""
        description = e.get("description", "") or ""

        responses = e.get("responses", {})
        accepted = len(responses.get("acceptedIds", []))
        declined = len(responses.get("declinedIds", []))
        unanswered = len(responses.get("unrespondedIds", []))

        # Detect our own RSVP (check if we appear in any list)
        # The spond library returns our own response in acceptedIds etc.
        # We'll mark as pending if we appear in unrespondedIds
        my_rsvp = "unknown"
        if responses.get("unrespondedIds"):
            my_rsvp = "pending"
        if responses.get("acceptedIds"):
            my_rsvp = "accepted"  # simplified — we assume we accepted if in list

        requires_response = 1 if my_rsvp == "pending" else 0

        # Check existing
        existing = c.execute(
            "SELECT rsvp_accepted, rsvp_declined, my_rsvp FROM spond_events WHERE id = ?",
            (eid,)
        ).fetchone()

        raw = json.dumps(e, ensure_ascii=False, default=str)

        if not existing:
            c.execute("""
                INSERT INTO spond_events
                    (id, group_id, group_name, member_id, title, event_date, event_end,
                     location, description, rsvp_accepted, rsvp_declined, rsvp_unanswered,
                     my_rsvp, requires_response, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (eid, group_id, group_name, member_id, title, start, end,
                  location, description, accepted, declined, unanswered,
                  my_rsvp, requires_response, raw))
            new_events.append({
                "id": eid, "title": title, "date": start,
                "group": group_name, "member_id": member_id,
                "my_rsvp": my_rsvp, "requires_response": requires_response,
                "location": location
            })
        else:
            prev_accepted, prev_declined, prev_rsvp = existing
            if prev_accepted != accepted or prev_declined != declined or prev_rsvp != my_rsvp:
                c.execute("""
                    UPDATE spond_events
                    SET rsvp_accepted=?, rsvp_declined=?, rsvp_unanswered=?,
                        my_rsvp=?, requires_response=?, raw_json=?,
                        last_updated=datetime('now')
                    WHERE id=?
                """, (accepted, declined, unanswered, my_rsvp, requires_response, raw, eid))
                changed_events.append({
                    "id": eid, "title": title, "date": start,
                    "group": group_name, "member_id": member_id,
                    "my_rsvp": my_rsvp, "requires_response": requires_response,
                    "change": f"rsvp {prev_accepted}→{accepted} accepted"
                })

    return new_events, changed_events, None


async def run_sync():
    load_secrets()
    from spond import spond as spond_lib

    s = spond_lib.Spond(
        username=os.environ["SPOND_USERNAME"],
        password=os.environ["SPOND_PASSWORD"]
    )
    # Spond moved authentication from /login to /auth2/login in May 2026.
    # The installed 1.1.1 client still supports Python 3.9, so patch only the
    # login flow instead of replacing the system Python runtime.
    s.login = types.MethodType(login_auth2, s)

    conn = get_db()
    c = conn.cursor()
    ensure_schema(c)
    conn.commit()

    all_new = []
    all_changed = []
    failures = []

    for group_id, (group_name, member_id) in SPOND_GROUPS.items():
        new, changed, error = await fetch_all(s, group_id, group_name, member_id, conn)
        all_new.extend(new)
        all_changed.extend(changed)
        if error:
            failures.append({"group": group_name, "error": error})
        print(f"  {group_name}: {len(new)} new, {len(changed)} changed")

    conn.commit()
    conn.close()
    await s.clientsession.close()

    # Also populate calendar_events from spond_events
    conn = get_db()
    c = conn.cursor()
    spond_rows = c.execute("""
        SELECT id, member_id, group_name, title, event_date, location, my_rsvp, requires_response
        FROM spond_events
        WHERE event_date >= date('now', '-7 days')
    """).fetchall()

    for row in spond_rows:
        eid, mid, gname, title, edate, loc, rsvp, req_resp = row
        # INSERT OR IGNORE: only write if this exact (member, title, date, source, source_ref) doesn't exist
        # This prevents duplicate rows on every sync run
        c.execute("""
            INSERT OR IGNORE INTO calendar_events
                (member_id, title, event_date, location, requires_response, source, source_ref)
            VALUES (?, ?, ?, ?, ?, 'spond', ?)
        """, (mid, title, edate, loc, req_resp, eid))
        # If already exists, update mutable fields only
        c.execute("""
            UPDATE calendar_events
            SET location=?, requires_response=?
            WHERE member_id=? AND title=? AND event_date=? AND source='spond' AND source_ref=?
        """, (loc, req_resp, mid, title, edate, eid))

    conn.commit()
    conn.close()

    # Pending RSVPs
    conn = get_db()
    c = conn.cursor()
    pending = c.execute("""
        SELECT title, event_date, group_name, member_id
        FROM spond_events
        WHERE requires_response = 1
          AND event_date >= date('now')
        ORDER BY event_date
    """).fetchall()
    conn.close()

    return {
        "new": all_new,
        "changed": all_changed,
        "pending_rsvp": [
            {"title": r[0], "date": r[1], "group": r[2], "member_id": r[3]}
            for r in pending
        ],
        "failures": failures,
    }


if __name__ == "__main__":
    print(f"[{datetime.now(OSLO).strftime('%Y-%m-%d %H:%M %Z')}] Syncing Spond...")
    result = asyncio.run(run_sync())
    state = {
        "checked_at": datetime.now(OSLO).isoformat(),
        "ok": not result["failures"],
        "failures": result["failures"],
        "new": len(result["new"]),
        "changed": len(result["changed"]),
    }
    atomic_write_json(STATE_PATH, state)
    print(f"\nNew events:     {len(result['new'])}")
    print(f"Changed events: {len(result['changed'])}")
    print(f"Pending RSVPs:  {len(result['pending_rsvp'])}")
    if result["pending_rsvp"]:
        print("\nPending RSVPs:")
        for r in result["pending_rsvp"]:
            print(f"  - {r['date']}: {r['title']} ({r['group']})")
    if result["new"]:
        print("\nNew events:")
        for e in result["new"]:
            print(f"  - {e['date']}: {e['title']} ({e['group']})")
    if result["failures"]:
        print(f"\nSpond sync failed for {len(result['failures'])} group(s).", file=sys.stderr)
        sys.exit(2)
