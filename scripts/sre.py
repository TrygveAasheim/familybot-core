#!/usr/bin/env python3
"""Shared schedule contracts and safe launchd inspection helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import zoneinfo


OSLO = zoneinfo.ZoneInfo("Europe/Oslo")


@dataclass(frozen=True)
class JobSpec:
    label: str
    task: str
    kind: str
    interval_seconds: Optional[int] = None
    calendar: tuple[tuple[int, int, int], ...] = ()
    max_runtime_seconds: int = 600
    auto_recover: bool = False


JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec("familybot.email", "email", "interval", interval_seconds=900, max_runtime_seconds=600, auto_recover=True),
    JobSpec("familybot.spond", "spond", "interval", interval_seconds=3600, max_runtime_seconds=900, auto_recover=True),
    JobSpec("familybot.health", "health", "interval", interval_seconds=1800, max_runtime_seconds=600),
    JobSpec("familybot.status", "status", "interval", interval_seconds=1800, max_runtime_seconds=600, auto_recover=True),
    JobSpec(
        "familybot.briefing.weekday", "briefing-daily", "calendar",
        calendar=((1, 6, 45), (2, 6, 45), (3, 6, 45), (4, 6, 45), (5, 6, 45)),
        max_runtime_seconds=900,
    ),
    JobSpec(
        "familybot.briefing.weekend", "briefing-daily", "calendar",
        calendar=((0, 8, 0), (6, 8, 0)), max_runtime_seconds=900,
    ),
    JobSpec(
        "familybot.briefing.weekly", "briefing-weekly", "calendar",
        calendar=((0, 21, 0),), max_runtime_seconds=900,
    ),
    JobSpec("familybot.delivery", "delivery", "interval", interval_seconds=300, max_runtime_seconds=180, auto_recover=True),
    JobSpec("familybot.ukeplan", "ukeplan-interpret", "interval", interval_seconds=900, max_runtime_seconds=600, auto_recover=True),
    JobSpec("familybot.tbane", "tbane", "interval", interval_seconds=900, max_runtime_seconds=600, auto_recover=True),
)

JOB_BY_LABEL = {spec.label: spec for spec in JOB_SPECS}


@dataclass(frozen=True)
class LaunchdInfo:
    loaded: bool
    running: bool
    pid: Optional[int]
    runs: Optional[int]
    last_exit_code: Optional[int]


def parse_launchctl_output(output: str) -> LaunchdInfo:
    state_match = re.search(r"^\s*state = ([^\n]+)", output, re.MULTILINE)
    pid_match = re.search(r"^\s*pid = (\d+)", output, re.MULTILINE)
    runs_match = re.search(r"^\s*runs = (\d+)", output, re.MULTILINE)
    exit_match = re.search(r"^\s*last exit code = (-?\d+)", output, re.MULTILINE)
    return LaunchdInfo(
        loaded=True,
        running=bool(state_match and state_match.group(1).strip() == "running"),
        pid=int(pid_match.group(1)) if pid_match else None,
        runs=int(runs_match.group(1)) if runs_match else None,
        last_exit_code=int(exit_match.group(1)) if exit_match else None,
    )


def read_job_state(workspace: Path, task: str) -> dict[str, Any]:
    candidates = [workspace / "db" / "job_state" / f"{task}.json"]
    if task.startswith("familybot."):
        candidates.append(workspace / "db" / "job_state" / f"{task.removeprefix('familybot.')}.json")
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            continue
    return {}


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_calendar_due(spec: JobSpec, now: datetime) -> Optional[datetime]:
    """Return the most recent configured local calendar time not after now."""
    local_now = now.astimezone(OSLO)
    for offset in range(0, 8):
        candidate_date = local_now.date() - timedelta(days=offset)
        weekday = (candidate_date.weekday() + 1) % 7
        for configured_day, hour, minute in spec.calendar:
            if configured_day != weekday:
                continue
            candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=OSLO)
            if candidate <= local_now:
                return candidate.astimezone(timezone.utc)
    return None


def next_calendar_due(spec: JobSpec, now: datetime) -> Optional[datetime]:
    local_now = now.astimezone(OSLO)
    for offset in range(0, 8):
        candidate_date = local_now.date() + timedelta(days=offset)
        weekday = (candidate_date.weekday() + 1) % 7
        for configured_day, hour, minute in spec.calendar:
            if configured_day != weekday:
                continue
            candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=OSLO)
            if candidate > local_now:
                return candidate.astimezone(timezone.utc)
    return None


def plist_path(home: Path, label: str) -> Path:
    if label not in JOB_BY_LABEL:
        raise ValueError(f"unknown FamilyBot label: {label}")
    return home / "Library" / "LaunchAgents" / f"{label}.plist"
