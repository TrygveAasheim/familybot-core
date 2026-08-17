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

import json
import subprocess
import re
import os
import sys
from datetime import datetime
import zoneinfo

sys.path.insert(0, os.path.dirname(__file__))
from reliability import atomic_write_json, workspace_path
from family_config import integration, telegram_recipients

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
# No persistent status file needed — briefing fetches live at report time
STATE_FILE = workspace_path() / "db" / "tbane_alert_state.json"
VACATION_MODE_FILE = workspace_path() / "memory" / "vacation-mode.json"

TRANSPORT_CONFIG = integration("transport")
CONFIGURED_LINE = str(TRANSPORT_CONFIG.get("line") or "2")
ROUTE_DESCRIPTION = str(TRANSPORT_CONFIG.get("route_description") or f"linje {CONFIGURED_LINE}")
TBANE_LINE_2   = {CONFIGURED_LINE}
ALL_TBANE      = {'1', '2', '3', '4', '5', '6'}
SYSTEM_THRESHOLD = 4  # 4+ lines = system-wide

SKIP_KEYWORDS = ('forsinkels', 'delay', 'noe forsinket', 'minor delay',
                 'ikke egnet for rullestol', 'not suitable for wheelchair',
                 'stengt holdeplass', 'closed stop')

RECIPIENTS = [target for _, target in telegram_recipients()]
ENTUR_CLIENT = str(integration("entur").get("client_name") or "familybot-local")


def vacation_mode_active() -> bool:
    try:
        with open(VACATION_MODE_FILE) as f:
            data = json.load(f)
        return bool(data.get("enabled"))
    except Exception:
        return False


def fetch_disruptions() -> list[dict]:
    """Fetch active disruptions from Entur. Returns list of {lines, summary, key}."""
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "10",
             "-H", f"ET-Client-Name: {ENTUR_CLIENT}",
             "https://api.entur.io/realtime/v1/rest/sx?datasetId=RUT"],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []

        data = r.stdout
        situations = re.findall(r'<PtSituationElement>(.*?)</PtSituationElement>', data, re.DOTALL)
        disruptions = []

        for sit in situations:
            lines = set(re.findall(r'<LineRef>RUT:Line:(\d+)</LineRef>', sit))
            summaries_no = re.findall(r'<Summary[^>]*lang=["\']NO["\'][^>]*>([^<]+)</Summary>', sit)
            if not summaries_no:
                all_sum = re.findall(r'<Summary>([^<]+)</Summary>', sit)
                summaries_no = all_sum[::2] if len(all_sum) > 1 else all_sum

            summary = summaries_no[0].strip() if summaries_no else None
            if not summary:
                continue

            # Skip noise
            if any(kw in summary.lower() for kw in SKIP_KEYWORDS):
                continue

            tbane_lines = lines & ALL_TBANE
            if not tbane_lines:
                continue

            disruptions.append({
                "lines": sorted(tbane_lines),
                "summary": summary,
                "key": f"{','.join(sorted(tbane_lines))}:{summary[:50]}"
            })

        return disruptions

    except Exception as e:
        print(f"[tbane_monitor] fetch error: {e}")
        return []


def classify(disruptions: list[dict]) -> dict:
    """
    Returns:
      {
        "line2": [relevant disruptions for line 2],
        "system": [system-wide disruptions],
        "all_clear": bool
      }
    """
    line2 = []
    system = []

    for d in disruptions:
        lines = set(d["lines"])
        if len(lines & ALL_TBANE) >= SYSTEM_THRESHOLD:
            system.append(d)
        elif "2" in lines:
            line2.append(d)

    return {
        "line2": line2,
        "system": system,
        "all_clear": not line2 and not system,
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


def run():
    now = datetime.now(OSLO).strftime("%Y-%m-%d %H:%M %Z")
    disruptions = fetch_disruptions()
    classified = classify(disruptions)

    # Alert logic
    state = load_state()
    active = state.get("active_alerts", {})
    new_alerts = {}
    fired = []
    cleared = []

    # Build new alert set
    for d in classified["line2"] + classified["system"]:
        new_alerts[d["key"]] = d["summary"]

    # Fire on new alerts
    for key, summary in new_alerts.items():
        if key not in active:
            fired.append(summary)

    # Note cleared alerts
    for key in active:
        if key not in new_alerts:
            cleared.append(active[key])

    # Send alert if new disruptions
    # Only alert during daytime (07:30-22:00 Oslo)
    hour_min = datetime.now(OSLO).hour * 60 + datetime.now(OSLO).minute
    daytime = 7 * 60 + 30 <= hour_min <= 22 * 60

    if fired and daytime:
        lines_desc = ROUTE_DESCRIPTION if classified["line2"] and not classified["system"] else "T-banen"
        msg = f"T-bane avvik — {lines_desc}:\n" + "\n".join(f"- {s}" for s in fired)
        send_telegram(msg)

    # Update state
    state["active_alerts"] = new_alerts
    save_state(state)


if __name__ == "__main__":
    run()
