#!/usr/bin/env python3
"""Regenerate STATUS.md from the services that actually run FamilyBot."""
import json, os, sqlite3, subprocess
from datetime import datetime
import zoneinfo
import sys

sys.path.insert(0, os.path.dirname(__file__))
from reliability import atomic_write_text, connect_db, workspace_path
from family_config import integration, parents

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
WORKSPACE = workspace_path()
STATUS_PATH = WORKSPACE / "STATUS.md"
DB_PATH = WORKSPACE / "db" / "family.db"
VACATION_PATH = WORKSPACE / "memory" / "vacation-mode.json"
PARENT_NAMES = [str(item["name"]) for item in parents()]
EMAIL_ACCOUNT = str(integration("email").get("account") or "konfigurert konto")
JOBS = [
    ("familybot.email", "E-postimport", "hvert 15. minutt"),
    ("familybot.spond", "Spond-synk", "hver time"),
    ("familybot.health", "Helsesjekk", "hvert 30. minutt"),
    ("familybot.status", "Statusoppdatering", "hvert 30. minutt"),
    ("familybot.tbane", "T-baneovervåking", "hvert 15. minutt"),
    ("familybot.briefing.weekday", "Morgenbriefing", "06:45 mandag–fredag"),
    ("familybot.briefing.weekend", "Morgenbriefing helg", "08:00 lørdag–søndag"),
    ("familybot.briefing.weekly", "Søndagsoversikt", "21:00 søndag"),
    ("familybot.delivery", "Telegram-kø", "hvert 5. minutt"),
]

def launchd_state(label):
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return "ikke lastet", None
    state, last_exit = "planlagt", None
    for line in result.stdout.splitlines():
        item = line.strip()
        if item.startswith("state ="):
            state = "kjører" if item.endswith("running") else "planlagt"
        elif item.startswith("last exit code ="):
            try: last_exit = int(item.rsplit("=", 1)[1].strip())
            except ValueError: pass
    return state, last_exit

def vacation_active():
    try:
        with open(VACATION_PATH) as handle:
            return bool(json.load(handle).get("enabled"))
    except (OSError, ValueError):
        return False

conn = connect_db(DB_PATH)
c = conn.cursor()
tables = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
members = c.execute("SELECT name, role, grade FROM family_members").fetchall()
activities = c.execute("""SELECT m.name, a.name, a.schedule, a.spond_group_id
 FROM activities a JOIN family_members m ON a.member_id=m.id WHERE a.active=1""").fetchall()
email_freshness = c.execute("SELECT MAX(processed_at) FROM email_log").fetchone()[0]
spond_freshness = c.execute("SELECT MAX(last_updated) FROM spond_events").fetchone()[0]
conn.close()

lines = ["# STATUS.md — FamilyBot faktisk kjørende konfig", "",
         f"Sist oppdatert: {datetime.now(OSLO).strftime('%Y-%m-%d %H:%M %Z')}", "",
         "**Denne filen genereres fra launchd og SQLite.**", "",
         f"## Driftsmodus: {'feriemodus — utsendinger er pauset' if vacation_active() else 'normal'}", "",
         "## Planlagte jobber", ""]
for label, name, schedule in JOBS:
    state, last_exit = launchd_state(label)
    exit_text = "" if last_exit is None else f", sist exit={last_exit}"
    lines.append(f"- **{name}** — {schedule} [{state}{exit_text}]")
lines += ["", "## Datakilder", "", f"- E-post sist behandlet: {email_freshness or 'ingen'}",
          f"- Spond sist oppdatert: {spond_freshness or 'ingen vellykket synk'}",
          f"- SQLite-tabeller: {', '.join(tables)}", "", "## Familiemedlemmer"]
for name, role, grade in members:
    lines.append(f"- **{name}** ({role}{f', trinn {grade}' if grade else ''})")
lines += ["", "## Aktiviteter"]
for child, activity, schedule, spond_id in activities:
    lines.append(f"- **{child}**: {activity} ({schedule or '?'}) — Spond: {'ja' if spond_id else 'nei'}")
lines += ["", "## Integrasjoner", "",
          f"- Telegram: OpenClaw gateway, separate DM-sesjoner for {', '.join(PARENT_NAMES)}",
          f"- E-post: {EMAIL_ACCOUNT} via Himalaya/IMAP",
          "- Spond: uoffisiell API-klient; feil rapporteres eksplisitt",
          "- Database: db/family.db (SQLite)", ""]
atomic_write_text(STATUS_PATH, "\n".join(lines) + "\n")
print("STATUS.md oppdatert fra faktisk driftsstate.")
