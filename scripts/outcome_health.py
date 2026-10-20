"""Private, content-free outcome observations for the existing SRE loop."""

import json
from datetime import datetime, timedelta, timezone

from reliability import atomic_write_json, workspace_path


def record_briefing(kind, fallback):
    """One writer per kind (cron_runner lock); never store message content."""
    path = workspace_path() / "memory" / f"briefing-outcome-{kind}.json"
    atomic_write_json(path, {
        "fallback": bool(fallback),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })


def briefing_health():
    degraded = False
    unreadable = False
    for kind, days in (("daily", 2), ("weekly", 8)):
        path = workspace_path() / "memory" / f"briefing-outcome-{kind}.json"
        try:
            state = json.loads(path.read_text())
            checked = datetime.fromisoformat(state["checked_at"])
            if datetime.now(timezone.utc) - checked < timedelta(days=days):
                degraded |= bool(state["fallback"])
        except FileNotFoundError:
            continue  # No observation yet; scheduler owns missing/stale runs.
        except (OSError, ValueError, KeyError, TypeError):
            unreadable = True
    return {
        "service": "briefing_quality",
        "status": "warn" if degraded or unreadable else "ok",
        "msg": ("Recent briefing used deterministic fallback; inspect model availability or validation"
                if degraded else "Outcome record unreadable" if unreadable
                else "No recent degraded briefing observed"),
    }


def interpretation_health(connection, today):
    """Only current/next-week plans: historical failures must not page forever."""
    periods = {today.isocalendar()[:2], (today + timedelta(days=7)).isocalendar()[:2]}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"week_plans", "week_plan_interpretations"} <= tables:
        return {"service": "ukeplan_quality", "status": "ok", "msg": "Interpretations not initialized"}
    failed = False
    for year, week in periods:
        rows = connection.execute(
            """SELECT i.status, i.updated_at FROM week_plans w
               LEFT JOIN week_plan_interpretations i ON i.week_plan_id=w.id
               WHERE w.year=? AND w.week_number=? AND COALESCE(w.layout_json,'')<>''""",
            (year, week),
        )
        for status, updated in rows:
            if status == "failed":
                failed = True
            elif status != "accepted":
                try:
                    stamp = datetime.fromisoformat(updated)
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    failed |= datetime.now(timezone.utc) - stamp > timedelta(hours=1)
                except (ValueError, TypeError):
                    failed = True
    return {"service": "ukeplan_quality", "status": "warn" if failed else "ok",
            "msg": "Current/next-week interpretation needs attention" if failed
            else "No blocked current/next-week interpretation observed"}
