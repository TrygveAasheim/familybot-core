"""Private, content-free outcome observations for the existing SRE loop."""

import json
from datetime import datetime, timedelta, timezone

from reliability import atomic_write_json, workspace_path

BRIEFING_WINDOWS = {"daily": 2, "weekly": 8}
BRIEFING_REASONS = {"empty_model_output", "validation_rejected", "unknown", "none"}


def read_briefing(kind):
    if kind not in BRIEFING_WINDOWS:
        raise ValueError("Unknown briefing kind")
    path = workspace_path() / "memory" / f"briefing-outcome-{kind}.json"
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or type(state.get("fallback")) is not bool:
        raise ValueError("Invalid briefing outcome")
    checked = datetime.fromisoformat(state["checked_at"])
    age = datetime.now(timezone.utc) - checked
    if age < timedelta(0):
        raise ValueError("Future briefing outcome")
    if age >= timedelta(days=BRIEFING_WINDOWS[kind]):
        return None
    count = state.get("consecutive_fallbacks", int(state["fallback"]))
    if type(count) is not int or not 0 <= count <= 1000:
        raise ValueError("Invalid briefing count")
    if (state["fallback"] and count == 0) or (not state["fallback"] and count != 0):
        raise ValueError("Inconsistent briefing count")
    since = datetime.fromisoformat(state.get("fallback_since") or state["checked_at"])
    if since.tzinfo is None or since > checked:
        raise ValueError("Invalid briefing streak timestamp")
    return {"checked_at": checked.isoformat(), "fallback": state["fallback"],
            "consecutive_fallbacks": count,
            "fallback_since": since.isoformat() if state["fallback"] else None,
            "reason": state.get("reason") if state.get("reason") in BRIEFING_REASONS else "unknown"}


def record_briefing(kind, fallback, reason="unknown"):
    """One writer per kind (cron_runner lock); never store message content."""
    if kind not in BRIEFING_WINDOWS:
        raise ValueError("Unknown briefing kind")
    try:
        previous = read_briefing(kind)
    except (OSError, ValueError, KeyError, TypeError):
        previous = None
    count = (previous or {}).get("consecutive_fallbacks", 0) + 1 if fallback else 0
    checked = datetime.now(timezone.utc).isoformat()
    path = workspace_path() / "memory" / f"briefing-outcome-{kind}.json"
    atomic_write_json(path, {
        "fallback": bool(fallback),
        "checked_at": checked,
        "consecutive_fallbacks": min(count, 1000),
        "fallback_since": ((previous or {}).get("fallback_since") or checked) if fallback else None,
        "reason": (reason if reason in BRIEFING_REASONS else "unknown") if fallback else "none",
    })


def briefing_health(kinds=("daily", "weekly")):
    observations = []
    unreadable = False
    for kind in kinds:
        try:
            state = read_briefing(kind)
            if state:
                observations.append({"kind": kind, **state})
        except FileNotFoundError:
            continue  # No observation yet; scheduler owns missing/stale runs.
        except (OSError, ValueError, KeyError, TypeError):
            unreadable = True
    degraded = [item for item in observations if item["fallback"]]
    if unreadable:
        message = "Outcome record unreadable"
    elif degraded:
        message = "Deterministic fallback used; delivery is monitored separately. " + "; ".join(
            f"{item['kind']}: {item['reason']} ({item['checked_at']})" for item in degraded
        )
    else:
        message = "No recent degraded briefing observed"
    result = {
        "service": "briefing_quality",
        "status": "warn" if degraded or unreadable else "ok",
        "msg": message,
        "observations": observations,
    }
    if not unreadable:
        result["consecutive_briefings"] = max(
            (item["consecutive_fallbacks"] for item in observations), default=0,
        )
        result["briefing_incident"] = ";".join(
            f"{item['kind']}:{item['fallback_since']}" for item in degraded
            if item["consecutive_fallbacks"] == result["consecutive_briefings"]
        )
    return result


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
