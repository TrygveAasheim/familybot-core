#!/usr/bin/env python3
"""Regenerate STATUS.md from the services that actually run FamilyBot."""
import json
import os
import subprocess
import zoneinfo
from datetime import datetime

from family_config import capability_profile, family_timezone, integration, parents
from reliability import atomic_write_text, connect_db, workspace_path
from sre import active_job_specs, read_job_state

LOCAL_ZONE = zoneinfo.ZoneInfo(family_timezone())
PROFILE = capability_profile()
WORKSPACE = workspace_path()
STATUS_PATH = WORKSPACE / "STATUS.md"
DB_PATH = WORKSPACE / "db" / "family.db"
VACATION_PATH = WORKSPACE / "memory" / "vacation-mode.json"
PARENT_NAMES = [str(item["name"]) for item in parents()]
EMAIL_ACCOUNT = str(integration("email").get("account") or "konfigurert konto")
JOB_NAMES = {
    "familybot.email": "E-postimport",
    "familybot.spond": "Spond-synk",
    "familybot.health": "Helsesjekk",
    "familybot.status": "Statusoppdatering",
    "familybot.tbane": "Kollektivovervåking",
    "familybot.briefing.weekday": "Morgenbriefing",
    "familybot.briefing.weekend": "Morgenbriefing helg",
    "familybot.briefing.weekly": "Ukesoversikt",
    "familybot.delivery": "Telegram-kø",
    "familybot.ukeplan": "Ukeplanforståelse",
}
JOBS = active_job_specs()

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
            try:
                last_exit = int(item.rsplit("=", 1)[1].strip())
            except ValueError:
                pass
    execution = read_job_state(WORKSPACE, label)
    if execution:
        if execution.get("status") == "running":
            state = "kjører"
        recorded_exit = execution.get("last_exit_code")
        if isinstance(recorded_exit, int):
            last_exit = recorded_exit
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
         f"Sist oppdatert: {datetime.now(LOCAL_ZONE).strftime('%Y-%m-%d %H:%M %Z')}", "",
         "**Denne filen genereres fra launchd og SQLite.**", "",
         f"## Profil: {PROFILE}", "",
         f"Driftsmodus: {'feriemodus — utsendinger er pauset' if vacation_active() else 'normal'}", "",
         "## Planlagte jobber", ""]
for spec in JOBS:
    state, last_exit = launchd_state(spec.label)
    exit_text = "" if last_exit is None else f", sist exit={last_exit}"
    schedule = (
        f"hvert {int((spec.interval_seconds or 0) / 60)}. minutt"
        if spec.kind == "interval"
        else "konfigurert klokkeslett"
    )
    lines.append(f"- **{JOB_NAMES[spec.label]}** — {schedule} [{state}{exit_text}]")
if not JOBS:
    lines.append("- Ingen Core-jobber i dashboard-profilen")
lines += ["", "## Datakilder", "", f"- E-post sist behandlet: {email_freshness or 'ingen'}",
          f"- Spond sist oppdatert: {spond_freshness or 'ingen vellykket synk'}",
          f"- SQLite-tabeller: {', '.join(tables)}", "", "## Familiemedlemmer"]
for name, role, grade in members:
    lines.append(f"- **{name}** ({role}{f', trinn {grade}' if grade else ''})")
lines += ["", "## Aktiviteter"]
for child, activity, schedule, spond_id in activities:
    lines.append(f"- **{child}**: {activity} ({schedule or '?'}) — Spond: {'ja' if spond_id else 'nei'}")
lines += ["", "## Integrasjoner", ""]
lines.append(
    f"- Telegram: OpenClaw gateway for {', '.join(PARENT_NAMES)}"
    if PROFILE == "agent"
    else "- Telegram/AI: ikke aktivert"
)
lines.append(
    f"- E-post: {EMAIL_ACCOUNT} via Himalaya/IMAP"
    if integration("email")
    else "- E-post: ikke aktivert"
)
lines.append(
    "- Spond: uoffisiell API-klient; feil rapporteres eksplisitt"
    if integration("spond").get("groups")
    else "- Spond: ikke aktivert"
)
lines += ["- Database: db/family.db (SQLite)", ""]
atomic_write_text(STATUS_PATH, "\n".join(lines) + "\n")
print("STATUS.md oppdatert fra faktisk driftsstate.")
