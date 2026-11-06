#!/usr/bin/env python3
"""
T-bane monitor for FamilyBot.

Fetches disruption status for Ruter T-bane via Entur realtime API every 15 min.
- Stores current status in db/tbane_status.json
- Alerts the configured parents on Telegram if:
    * New disruption on the locally configured transit line
    * New system-wide disruption (4+ lines affected)
- Silent if no change or only minor delays

State tracking: db/tbane_alert_state.json
  {"active_alerts": {"key": "summary", ...}}
  Alerts fire once when new, clear when resolved.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
import zoneinfo
from datetime import datetime
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(__file__))
from family_config import family_timezone, integration, telegram_recipients
from reliability import atomic_write_json, workspace_path
from transport_relevance import classify_for_corridor, parse_siri_disruptions

LOCAL_ZONE = zoneinfo.ZoneInfo(family_timezone())
# No persistent status file needed — briefing fetches live at report time
STATE_FILE = workspace_path() / "db" / "tbane_alert_state.json"
VACATION_MODE_FILE = workspace_path() / "memory" / "vacation-mode.json"

TRANSPORT_CONFIG = integration("transport")
CONFIGURED_LINE = str(TRANSPORT_CONFIG.get("line") or "2")
ROUTE_DESCRIPTION = str(TRANSPORT_CONFIG.get("route_description") or f"linje {CONFIGURED_LINE}")
ALERT_STOPS = tuple(str(value) for value in TRANSPORT_CONFIG.get("alert_stops", []) if str(value).strip())
ALERT_STOP_IDS = tuple(str(value) for value in TRANSPORT_CONFIG.get("alert_stop_ids", []) if str(value).strip())
ALL_TBANE      = {'1', '2', '3', '4', '5', '6'}
SYSTEM_THRESHOLD = 4  # 4+ lines = system-wide

RECIPIENTS = [target for _, target in telegram_recipients()]
ENTUR_CLIENT = str(integration("entur").get("client_name") or "familybot-local")


def vacation_mode_active() -> bool:
    try:
        with open(VACATION_MODE_FILE) as f:
            data = json.load(f)
        return bool(data.get("enabled"))
    except Exception:
        return False


def fetch_disruptions() -> list[dict] | None:
    """Fetch disruptions, or ``None`` when Entur could not be read reliably."""
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "10",
             "-H", f"ET-Client-Name: {ENTUR_CLIENT}",
             "https://api.entur.io/realtime/v1/rest/sx?datasetId=RUT"],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None

        return parse_siri_disruptions(r.stdout, ALL_TBANE)

    except Exception as e:
        print(f"[tbane_monitor] fetch error: {e}")
        return None


def normalized_summary(value: object) -> str:
    """Normalize cosmetic API changes so they do not create a new alert."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\wæøå]+", " ", text).split())


def alert_fingerprint(disruption: dict) -> str:
    lines = ",".join(sorted(str(line) for line in disruption.get("lines", [])))
    return f"{lines}:{normalized_summary(disruption.get('summary'))}"


def summaries_similar(left: object, right: object) -> bool:
    """Treat punctuation and small wording edits as the same notice."""
    a, b = normalized_summary(left), normalized_summary(right)
    if not a or not b:
        return a == b
    if a == b:
        return True
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(len(a_tokens | b_tokens), 1)
    return overlap >= 0.75 or SequenceMatcher(None, a, b).ratio() >= 0.86


def classify(disruptions: list[dict]) -> dict:
    """
    Returns:
      {
        "line2": [relevant disruptions for line 2],
        "system": [system-wide disruptions],
        "all_clear": bool
      }
    """
    relevant = classify_for_corridor(
        disruptions, CONFIGURED_LINE, ALERT_STOPS, ALERT_STOP_IDS,
        all_lines=ALL_TBANE, system_threshold=SYSTEM_THRESHOLD,
    )

    return {
        "line2": relevant["route"],
        "system": relevant["system"],
        "all_clear": not relevant["route"] and not relevant["system"],
    }


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"active_alerts": {}}


def save_state(state: dict):
    atomic_write_json(STATE_FILE, state)


def send_telegram(message: str):
    if vacation_mode_active():
        print("[tbane_monitor] Vacation mode active; Telegram send skipped.")
        return
    for target in RECIPIENTS:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "telegram",
             "--target", target,
             "--message", message],
            capture_output=True
        )


def reconcile_alerts(classified: dict, state: dict, observed_at: datetime) -> tuple[dict, list[str]]:
    """Update durable alert history and return summaries that are genuinely new."""
    active = dict(state.get("active_alerts", {}))
    notified = dict(state.get("notified_alerts", {}))
    new_alerts = {
        alert_fingerprint(disruption): disruption["summary"]
        for disruption in classified["line2"] + classified["system"]
    }
    fired = []

    for key, summary in new_alerts.items():
        previously_notified = (
            key in notified
            or any(summaries_similar(summary, old_summary) for old_summary in active.values())
            or any(
                summaries_similar(summary, record.get("summary") if isinstance(record, dict) else record)
                for record in notified.values()
            )
        )
        if not previously_notified:
            fired.append(summary)

    observed_text = observed_at.isoformat(timespec="seconds")
    for key, summary in new_alerts.items():
        # Cache every observed notice, including similar variants, so it cannot
        # re-alert after a transient all-clear or process restart.
        notified[key] = {"summary": summary, "last_seen": observed_text}

    updated = dict(state)
    updated["active_alerts"] = new_alerts
    updated["notified_alerts"] = notified
    return updated, fired


def run():
    disruptions = fetch_disruptions()
    # A timeout or malformed/empty response is not an all-clear. Keep the cache
    # unchanged so a temporary Entur failure cannot make an old notice look new.
    if disruptions is None:
        print("[tbane_monitor] Fetch failed; keeping previous alert cache.")
        return
    classified = classify(disruptions)

    # Alert logic
    state = load_state()
    now = datetime.now(LOCAL_ZONE)
    state, fired = reconcile_alerts(classified, state, now)

    # Send alert if new disruptions
    # Only alert during daytime (07:30-22:00 in the household time zone).
    hour_min = now.hour * 60 + now.minute
    daytime = 7 * 60 + 30 <= hour_min <= 22 * 60

    if fired and daytime:
        lines_desc = ROUTE_DESCRIPTION if classified["line2"] and not classified["system"] else "T-banen"
        msg = f"T-bane avvik — {lines_desc}:\n" + "\n".join(f"- {s}" for s in fired)
        send_telegram(msg)

    save_state(state)


if __name__ == "__main__":
    run()
