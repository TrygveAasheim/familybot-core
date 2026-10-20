#!/usr/bin/env python3
"""Perform bounded, auditable recovery for the local FamilyBot appliance.

This is intentionally separate from healthcheck.py.  A health probe observes;
this script may act, and only on an explicit allowlist of safe recoveries.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from reliability import atomic_write_json, workspace_path
from family_config import telegram_recipients
from sre import JOB_SPECS, JobSpec, LaunchdInfo, parse_timestamp, plist_path, read_job_state


COOLDOWN = timedelta(minutes=15)
GATEWAY_FAILURE_THRESHOLD = 2
HEALTH_ALERT_THRESHOLD = 3
HEALTH_FAILURE_KEYS = {
    "briefing_quality",
    "ukeplan_quality",
    "gateway",
    "telegram",
    "email",
    "database",
    "delivery_outbox",
    "email_pipeline",
    "scheduler",
    "spond",
    "disk",
    "calendar_hygiene",
    "email_processing",
    "cron",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (OSError, ValueError):
        return default.copy()


def launchd_info(label: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Optional[LaunchdInfo]:
    result = runner(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    from sre import parse_launchctl_output

    return parse_launchctl_output(result.stdout)


def secure_plist(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return path.is_file() and stat.st_uid == os.getuid() and stat.st_mode & 0o077 == 0


def cooldown_allows(action_key: str, state: dict[str, Any], current: datetime) -> bool:
    previous = parse_timestamp(state.get("actions", {}).get(action_key))
    return previous is None or current - previous >= COOLDOWN


def overdue(spec: JobSpec, state: dict[str, Any], current: datetime) -> bool:
    finished = parse_timestamp(state.get("finished_at"))
    if not finished or spec.kind != "interval" or not spec.interval_seconds:
        return False
    return current - finished > timedelta(seconds=spec.interval_seconds + spec.max_runtime_seconds)


def health_event_key(result: dict[str, Any]) -> str:
    """Build a stable key for one unchanged failure, without raw payloads."""
    service = str(result.get("service", "unknown"))[:80]
    if service == "scheduler":
        active = result.get("jobs", [])
        return f"{service}:{json.dumps(active, sort_keys=True, ensure_ascii=True)[:500]}"
    return f"{service}:{str(result.get('msg', 'failure'))[:300]}"


def update_health_failures(
    status: dict[str, Any],
    previous: dict[str, Any],
    current: datetime,
    threshold: int = HEALTH_ALERT_THRESHOLD,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Own consecutive failure counters and return newly eligible alerts."""
    records = previous.setdefault("health_failures", {})
    checked_at = str(status.get("checked_at") or current.isoformat(timespec="seconds"))
    duplicate_observation = previous.get("last_health_checked_at") == checked_at
    alerts: list[dict[str, Any]] = []
    counters = {key: 0 for key in HEALTH_FAILURE_KEYS}

    for result in status.get("results", []):
        service = str(result.get("service", ""))
        if service not in HEALTH_FAILURE_KEYS:
            continue
        failed = result.get("status") in {"warn", "critical"}
        record = records.get(service, {})
        event_key = health_event_key(result) if failed else ""
        if duplicate_observation:
            count = int(record.get("count", 0))
        elif failed:
            count = int(record.get("count", 0)) + 1 if record.get("event_key") == event_key else 1
            records[service] = {
                "count": count,
                "event_key": event_key,
                "last_seen": checked_at,
                "alerted": bool(record.get("alerted", False)) if record.get("event_key") == event_key else False,
            }
        else:
            count = 0
            records[service] = {"count": 0, "event_key": "", "last_seen": checked_at, "alerted": False}
        counters[service] = count
        if failed and count >= threshold and not records.get(service, {}).get("alerted"):
            alerts.append({
                "service": service,
                "status": str(result.get("status")),
                "count": count,
                "msg": str(result.get("msg", "failure"))[:300],
                "event_key": event_key,
            })

    previous["last_health_checked_at"] = checked_at
    previous["health_failures"] = records
    return counters, alerts


def send_health_alert(alert: dict[str, Any]) -> tuple[bool, str]:
    """Send one deduplicated owner alert; return success and bounded detail."""
    configured = os.environ.get("FAMILYBOT_SRE_ALERT_TARGET", "").strip()
    targets = [configured] if configured else [target for _, target in telegram_recipients()]
    if not targets:
        return False, "no configured Telegram alert target"
    message = (
        f"Health check alert: {alert['service']} has reached {alert['count']} consecutive failures. "
        f"Status: {alert['status']}. SRE analysis: {alert['msg']}"
    )
    for target in targets[:1]:
        try:
            result = subprocess.run(
                ["openclaw", "message", "send", "--channel", "telegram", "--target", target, "--message", message],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)[:200]
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "Telegram send failed").strip()[:200]
    return True, "sent"


def plan_actions(
    *,
    home: Path,
    launchd: dict[str, Optional[LaunchdInfo]],
    states: dict[str, dict[str, Any]],
    current: datetime,
    previous: dict[str, Any],
    gateway_failures: int = 0,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for spec in JOB_SPECS:
        if not spec.auto_recover:
            continue
        info = launchd.get(spec.label)
        if info is None:
            plist = plist_path(home, spec.label)
            if secure_plist(plist) and cooldown_allows(f"bootstrap:{spec.label}", previous, current):
                actions.append({
                    "kind": "bootstrap",
                    "label": spec.label,
                    "argv": ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
                    "reason": "LaunchAgent is not loaded",
                })
            continue

        state = states.get(spec.label, {})
        if state.get("status") == "running":
            started = parse_timestamp(state.get("started_at"))
            stuck = bool(started and current - started > timedelta(seconds=spec.max_runtime_seconds))
        else:
            stuck = False
        recoverable_failure = state.get("status") == "failed" and overdue(spec, state, current)
        missed_interval = overdue(spec, state, current)
        action_key = f"kickstart:{spec.label}"
        if (stuck or recoverable_failure or missed_interval) and cooldown_allows(action_key, previous, current):
            actions.append({
                "kind": "kickstart",
                "label": spec.label,
                "argv": [
                    "launchctl",
                    "kickstart",
                    "-k" if stuck else "",
                    f"gui/{os.getuid()}/{spec.label}",
                ],
                "reason": "stale or overdue interval job",
            })

    if gateway_failures >= GATEWAY_FAILURE_THRESHOLD and cooldown_allows("gateway:restart", previous, current):
        actions.append({
            "kind": "gateway_restart",
            "label": "openclaw.gateway",
            "argv": ["openclaw", "gateway", "restart"],
            "reason": f"gateway health failed {gateway_failures} consecutive checks",
        })
    return actions


def acquire_lock(path: Path) -> bool:
    try:
        path.mkdir(mode=0o700)
        (path / "pid").write_text(str(os.getpid()), encoding="ascii")
        os.chmod(path / "pid", 0o600)
        return True
    except FileExistsError:
        try:
            pid = int((path / "pid").read_text(encoding="ascii").strip())
            os.kill(pid, 0)
            return False
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            try:
                (path / "pid").unlink(missing_ok=True)
                path.rmdir()
            except OSError:
                return False
            return acquire_lock(path)


def release_lock(path: Path) -> None:
    try:
        (path / "pid").unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass


def append_audit(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print planned actions without executing them")
    args = parser.parse_args()

    workspace = workspace_path()
    db_dir = workspace / "db"
    lock = db_dir / ".sre-reconcile.lock"
    if not acquire_lock(lock):
        print("[sre] another reconciliation is already running")
        return 0

    try:
        current = now()
        status = load_json(db_dir / "health_status.json", {})
        state_path = db_dir / "sre_state.json"
        previous = load_json(state_path, {"actions": {}, "failures": {}})
        counters, pending_alerts = update_health_failures(status, previous, current)
        if not args.dry_run:
            atomic_write_json(db_dir / "health_failures.json", counters)
            os.chmod(db_dir / "health_failures.json", 0o600)
        failures = previous.setdefault("failures", {})
        gateway_result = next((item for item in status.get("results", []) if item.get("service") == "gateway"), {})
        gateway_key = str(gateway_result.get("msg", "unknown"))
        gateway_record = failures.get("gateway", {})
        if gateway_result.get("status") == "critical":
            gateway_count = int(gateway_record.get("count", 0)) + 1 if gateway_record.get("key") == gateway_key else 1
            failures["gateway"] = {"count": gateway_count, "key": gateway_key, "last_seen": current.isoformat(timespec="seconds")}
        else:
            gateway_count = 0
            failures["gateway"] = {"count": 0, "key": gateway_key, "last_seen": current.isoformat(timespec="seconds")}

        launchd = {spec.label: launchd_info(spec.label) for spec in JOB_SPECS}
        states = {spec.label: read_job_state(workspace, spec.label) for spec in JOB_SPECS}
        actions = plan_actions(
            home=Path.home(),
            launchd=launchd,
            states=states,
            current=current,
            previous=previous,
            gateway_failures=gateway_count,
        )
        alert_results = []
        print(json.dumps({"dry_run": args.dry_run, "actions": actions, "health_failures": counters}, ensure_ascii=False))
        for action in actions:
            argv = [part for part in action["argv"] if part]
            entry = {
                "at": current.isoformat(timespec="seconds"),
                "kind": action["kind"],
                "label": action["label"],
                "reason": action["reason"],
                "dry_run": args.dry_run,
            }
            if args.dry_run:
                continue
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
                entry["exit_code"] = result.returncode
                if result.returncode == 0:
                    previous.setdefault("actions", {})[f"{action['kind']}:{action['label']}"] = current.isoformat(timespec="seconds")
                else:
                    entry["error"] = (result.stderr or result.stdout or "command failed").strip()[:300]
            except (OSError, subprocess.TimeoutExpired) as exc:
                entry["exit_code"] = -1
                entry["error"] = str(exc)[:300]
            append_audit(db_dir / "sre-actions.jsonl", entry)

        for alert in pending_alerts:
            if args.dry_run:
                alert_results.append({"service": alert["service"], "status": "dry-run"})
                continue
            sent, detail = send_health_alert(alert)
            alert_results.append({"service": alert["service"], "status": "sent" if sent else "failed", "detail": detail})
            if sent:
                previous["health_failures"][alert["service"]]["alerted"] = True
            append_audit(
                db_dir / "sre-actions.jsonl",
                {
                    "at": current.isoformat(timespec="seconds"),
                    "kind": "health_alert",
                    "label": alert["service"],
                    "reason": detail,
                    "dry_run": args.dry_run,
                },
            )

        if alert_results:
            print(json.dumps({"health_alerts": alert_results}, ensure_ascii=False))

        if not args.dry_run:
            atomic_write_json(state_path, previous)
            os.chmod(state_path, 0o600)
        return 0
    finally:
        release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
