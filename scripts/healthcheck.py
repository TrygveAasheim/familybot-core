#!/usr/bin/env python3
"""
FamilyBot health check script.
Checks all critical services and integrations, returns structured results.
Exit code 0 = all OK, 1 = warnings, 2 = critical failures.
"""

import subprocess
import sqlite3
import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import zoneinfo
sys.path.insert(0, os.path.dirname(__file__))
from reliability import connect_db, database_path, workspace_path
from family_config import integration

DB_PATH = str(database_path())
WORKSPACE = workspace_path()
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
EMAIL_ACCOUNT = str(integration("email").get("account") or "configured account")

results = []
exit_code = 0


def ok(service, msg):
    results.append({"service": service, "status": "ok", "msg": msg})


def warn(service, msg, fix=None):
    global exit_code
    exit_code = max(exit_code, 1)
    results.append({"service": service, "status": "warn", "msg": msg, "fix": fix})


def critical(service, msg, fix=None, auto_fix=None):
    global exit_code
    exit_code = max(exit_code, 2)
    results.append({"service": service, "status": "critical", "msg": msg,
                    "fix": fix, "auto_fix": auto_fix})


def run(cmd):
    try:
        env = os.environ.copy()
        env["HOME"] = str(Path.home())
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


# ── 1. OpenClaw gateway ────────────────────────────────────────────────────────
code, out, err = run("openclaw gateway status 2>&1 | grep -E 'Runtime:|RPC probe|Connectivity probe'")
out_lower = out.lower()
if "running" in out_lower and ("rpc probe: ok" in out_lower or "connectivity probe: ok" in out_lower):
    ok("gateway", "Running and connectivity probe OK")
else:
    critical("gateway", f"Gateway may be down: {out or err}",
             fix="openclaw gateway restart",
             auto_fix="restart")

# ── 2. Telegram channel ────────────────────────────────────────────────────────
code, out, err = run("openclaw status 2>&1 | grep -A1 'Telegram'")
if "OK" in out:
    ok("telegram", "Telegram channel connected")
else:
    warn("telegram", f"Telegram channel state unclear: {out}",
         fix="Check bot token and restart gateway")

# ── 3. Email / himalaya ───────────────────────────────────────────────────────
code, out, err = run("himalaya folder list --output json 2>/dev/null")
if code == 0 and "INBOX" in out:
    ok("email", f"himalaya IMAP connected to {EMAIL_ACCOUNT}")
else:
    critical("email", f"himalaya IMAP failed: {err or out}",
             fix="Check App Password and himalaya config at ~/.config/himalaya/config.toml")

# ── 4. Database ───────────────────────────────────────────────────────────────
try:
    conn = connect_db(DB_PATH)
    c = conn.cursor()
    quick_check = c.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        critical("database", f"SQLite quick_check failed: {quick_check}",
                 fix="Restore the latest verified database backup")
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    required = {"family_members", "calendar_events", "email_log",
                "kanban_cards", "school_calendar", "norwegian_holidays",
                "email_senders", "routing_audit"}
    missing = required - set(tables)
    if missing:
        critical("database", f"Missing tables: {missing}",
                 fix="Re-run calendar_seed.py and process_emails.py")
    else:
        member_count = c.execute("SELECT COUNT(*) FROM family_members").fetchone()[0]
        ok("database", f"SQLite OK — {len(tables)} tables, {member_count} family members")

    if "delivery_outbox" in tables:
        pending = c.execute(
            "SELECT COUNT(*) FROM delivery_outbox WHERE status IN ('pending', 'sending')"
        ).fetchone()[0]
        repeatedly_failed = c.execute(
            "SELECT COUNT(*) FROM delivery_outbox WHERE status='pending' AND attempts >= 3"
        ).fetchone()[0]
        if repeatedly_failed:
            critical("delivery_outbox", f"{repeatedly_failed} message(s) failed at least 3 times",
                     fix="Check Telegram/gateway, then run scripts/flush_outbox.py")
        elif pending:
            warn("delivery_outbox", f"{pending} message(s) awaiting delivery",
                 fix="Run scripts/flush_outbox.py or check familybot.delivery")
        else:
            ok("delivery_outbox", "No pending messages")
    else:
        warn("delivery_outbox", "Durable delivery outbox has not been initialized")

    if "email_processing_state" in tables:
        failed_email = c.execute(
            "SELECT COUNT(*) FROM email_processing_state WHERE status='failed'"
        ).fetchone()[0]
        if failed_email:
            warn("email_pipeline", f"{failed_email} email(s) remain retryable after failure",
                 fix="Inspect email_processing_state.last_error and rerun process_emails.py")
        else:
            ok("email_pipeline", "No failed email processing records")
    else:
        warn("email_pipeline", "Email processing ledger has not been initialized")
    conn.close()
except Exception as e:
    critical("database", f"Cannot open database: {e}",
             fix=f"Check {DB_PATH}")

# ── 5. Email processing freshness ─────────────────────────────────────────────

# ── 6. Cron jobs ──────────────────────────────────────────────────────────────
required_jobs = ["familybot.email", "familybot.spond", "familybot.health",
                 "familybot.status", "familybot.briefing.weekday",
                 "familybot.briefing.weekend", "familybot.briefing.weekly",
                 "familybot.delivery"]
missing_jobs, failed_jobs = [], []
for label in required_jobs:
    code, out, err = run(f"launchctl print gui/{os.getuid()}/{label}")
    if code != 0:
        missing_jobs.append(label)
        continue
    for line in out.splitlines():
        if "last exit code =" in line:
            try:
                if int(line.rsplit("=", 1)[1].strip()) != 0:
                    failed_jobs.append(label)
            except ValueError:
                pass
if missing_jobs:
    critical("scheduler", f"Missing launchd jobs: {', '.join(missing_jobs)}")
elif failed_jobs:
    warn("scheduler", f"Jobs with non-zero last exit: {', '.join(failed_jobs)}")
else:
    ok("scheduler", f"{len(required_jobs)} launchd jobs loaded")

try:
    with open(WORKSPACE / "db" / "spond_sync_state.json") as handle:
        spond_state = json.load(handle)
    if spond_state.get("ok"):
        ok("spond", f"Last sync OK at {spond_state.get('checked_at')}")
    else:
        warn("spond", f"Last sync failed at {spond_state.get('checked_at')}",
             fix="Repair or replace the unofficial Spond API client")
except (OSError, ValueError) as exc:
    warn("spond", f"No valid Spond sync state: {exc}")

# ── 7. Disk space ─────────────────────────────────────────────────────────────
code, out, err = run(f"df -h {WORKSPACE} 2>/dev/null | tail -1")
if code == 0 and out:
    parts = out.split()
    # macOS df: Filesystem Size Used Avail Capacity
    try:
        capacity = parts[4] if len(parts) > 4 else "?"
        avail = parts[3] if len(parts) > 3 else "?"
        pct = int(capacity.replace("%", ""))
        if pct > 90:
            critical("disk", f"Disk {pct}% full ({avail} free)",
                     fix="Free up space on Mac mini")
        elif pct > 75:
            warn("disk", f"Disk {pct}% full ({avail} free)")
        else:
            ok("disk", f"Disk {pct}% used ({avail} free)")
    except Exception:
        ok("disk", f"Disk check: {out}")


# ── 7b. Calendar hygiene — purge past email events ───────────────────────────
try:
    sys.path.insert(0, str(WORKSPACE / "scripts"))
    from calendar_guard import purge_past_email_events
    conn_hygiene = connect_db(DB_PATH)
    removed = purge_past_email_events(conn_hygiene, dry_run=True)
    conn_hygiene.close()
    if removed:
        warn("calendar_hygiene", f"{len(removed)} past email event(s) await cleanup")
    else:
        ok("calendar_hygiene", "No past email events to purge")
except Exception as e:
    warn("calendar_hygiene", f"Could not run calendar hygiene: {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
now = datetime.now(OSLO).strftime("%Y-%m-%d %H:%M %Z")
oks = [r for r in results if r["status"] == "ok"]
warns = [r for r in results if r["status"] == "warn"]
crits = [r for r in results if r["status"] == "critical"]

print(json.dumps({
    "checked_at": now,
    "summary": {"ok": len(oks), "warn": len(warns), "critical": len(crits)},
    "results": results
}, indent=2, ensure_ascii=False))

sys.exit(exit_code)
