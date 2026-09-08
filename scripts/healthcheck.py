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
from datetime import datetime, timedelta, timezone
from pathlib import Path
import zoneinfo
sys.path.insert(0, os.path.dirname(__file__))
from reliability import connect_db, database_path, workspace_path
from family_config import integration
from sre import (
    JOB_SPECS,
    latest_calendar_due,
    next_calendar_due,
    parse_launchctl_output,
    parse_timestamp,
    read_job_state,
)
from validate_launchd import validate_launchctl_output

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
# Fast status intentionally reports SETUP/unknown. Deep status performs the
# actual channel probe and is the only result suitable for health reporting.
code, out, err = run("openclaw status --deep 2>&1")
telegram_line = next((line for line in out.splitlines() if "telegram" in line.lower()), "")
if code == 0 and " OK " in f" {telegram_line.upper()} ":
    ok("telegram", "Telegram channel connected")
else:
    warn("telegram", f"Telegram channel state unclear: {telegram_line or err}",
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

# ── 6. Cron jobs and freshness ───────────────────────────────────────────────
now_utc = datetime.now(timezone.utc)
missing_jobs, active_failures, historical_failures, schedule_errors = [], [], [], []
job_details = []
for spec in JOB_SPECS:
    label = spec.label
    code, out, err = run(f"launchctl print gui/{os.getuid()}/{label}")
    if code != 0:
        missing_jobs.append(label)
        continue
    launchd_info = parse_launchctl_output(out)
    schedule_errors.extend(validate_launchctl_output(label, out))

    state = read_job_state(WORKSPACE, spec.label)
    finished = parse_timestamp(state.get("finished_at"))
    started = parse_timestamp(state.get("started_at"))
    state_exit = state.get("last_exit_code")
    last_exit = int(state_exit) if isinstance(state_exit, int) else launchd_info.last_exit_code
    next_due = next_calendar_due(spec, now_utc) if spec.kind == "calendar" else None
    latest_due = latest_calendar_due(spec, now_utc) if spec.kind == "calendar" else None
    detail = {
        "label": label,
        "state": state.get("status", "unknown"),
        "last_run": state.get("finished_at"),
        "last_exit": last_exit,
        "next_due": next_due.isoformat(timespec="seconds") if next_due else None,
    }
    job_details.append(detail)

    if state.get("status") == "running" and started:
        if (now_utc - started).total_seconds() > spec.max_runtime_seconds:
            active_failures.append(f"{label} has been running for too long")
        continue

    if state.get("status") == "failed":
        # A failed calendar job is actionable near its failed occurrence. Once
        # its failure is old and the next run is not due, keep the evidence in
        # the snapshot without turning every health poll into another alert.
        recent = bool(finished and (now_utc - finished).total_seconds() <= 36 * 3600)
        if spec.kind == "interval" or recent:
            active_failures.append(f"{label} last exited {last_exit}")
        else:
            historical_failures.append(f"{label} last exited {last_exit}")
        continue

    if state.get("status") == "success" and finished:
        if spec.kind == "interval":
            overdue = (now_utc - finished).total_seconds() > (spec.interval_seconds or 0) + spec.max_runtime_seconds
        else:
            overdue = bool(latest_due and finished < latest_due)
        if overdue:
            active_failures.append(f"{label} has no successful run since {finished.isoformat(timespec='seconds')}")
        continue

    # Legacy launchd jobs may have no execution-state file yet. Do not turn an
    # old launchd last-exit value into a repeated alert; the next run will be
    # recorded with a precise timestamp by cron_runner.sh.
    if launchd_info.last_exit_code not in (None, 0):
        historical_failures.append(f"{label} launchd last exit {launchd_info.last_exit_code} (legacy state)")
    elif (
        spec.kind == "calendar"
        and launchd_info.runs in (None, 0)
        and latest_due
        and latest_due < now_utc - timedelta(seconds=spec.max_runtime_seconds)
    ):
        active_failures.append(f"{label} has no recorded run for its latest scheduled occurrence")

if missing_jobs:
    critical("scheduler", f"Missing launchd jobs: {', '.join(missing_jobs)}")
elif schedule_errors:
    critical("scheduler", "; ".join(schedule_errors),
             fix="Run scripts/deploy_core.sh --reload from the reviewed core checkout")
elif active_failures:
    exit_code = max(exit_code, 1)
    results.append({
        "service": "scheduler",
        "status": "warn",
        "msg": "; ".join(active_failures),
        "fix": "Inspect the job state and let sre_reconcile.py recover allowlisted interval jobs",
        "jobs": job_details,
        "historical_failures": historical_failures,
    })
else:
    results.append({
        "service": "scheduler",
        "status": "ok",
        "msg": f"{len(JOB_SPECS)} launchd jobs loaded; no active freshness failures",
        "jobs": job_details,
        "historical_failures": historical_failures,
    })

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
now = datetime.now(OSLO)
oks = [r for r in results if r["status"] == "ok"]
warns = [r for r in results if r["status"] == "warn"]
crits = [r for r in results if r["status"] == "critical"]

payload = {
    "checked_at": now.isoformat(timespec="seconds"),
    "summary": {"ok": len(oks), "warn": len(warns), "critical": len(crits)},
    "results": results
}
status_path = WORKSPACE / "db" / "health_status.json"
status_path.parent.mkdir(parents=True, exist_ok=True)
temporary_path = status_path.with_suffix(".json.tmp")
temporary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
os.chmod(temporary_path, 0o600)
os.replace(temporary_path, status_path)
print(json.dumps(payload, indent=2, ensure_ascii=False))

sys.exit(exit_code)
