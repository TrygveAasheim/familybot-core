#!/usr/bin/env python3
"""Shared schedule contracts and safe launchd inspection helpers."""

from __future__ import annotations

import json
import re
import zoneinfo
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_ZONE = zoneinfo.ZoneInfo("Europe/Oslo")


def schedule_zone() -> zoneinfo.ZoneInfo:
    """Resolve the configured household zone while keeping diagnostics usable on bad config."""
    try:
        from family_config import family_timezone

        return zoneinfo.ZoneInfo(family_timezone())
    except (KeyError, RuntimeError, zoneinfo.ZoneInfoNotFoundError):
        return DEFAULT_ZONE


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


def active_job_specs(spond_enabled: Optional[bool] = None) -> tuple[JobSpec, ...]:
    """Return the health-owned jobs enabled by the local household config.

    Spond is an optional, unofficial integration.  A missing or empty groups
    list disables its schedule and health probe.  Invalid configuration keeps
    the complete contract active so a setup error cannot silently hide a job.
    """
    if spond_enabled is not None:
        if spond_enabled:
            return JOB_SPECS
        return tuple(spec for spec in JOB_SPECS if spec.label != "familybot.spond")
    try:
        from family_config import capability_profile, integration, notification_settings

        profile = capability_profile()
        notifications = notification_settings()
        enabled = set()
        if profile in {"connected", "agent"}:
            enabled.update({"familybot.health", "familybot.status"})
            if integration("email"):
                enabled.add("familybot.email")
            if integration("spond").get("groups"):
                enabled.add("familybot.spond")
            if integration("transport"):
                enabled.add("familybot.tbane")
        if profile == "agent":
            enabled.add("familybot.delivery")
            if notifications.get("weekday_briefing", True) is not False:
                enabled.add("familybot.briefing.weekday")
            if notifications.get("weekend_briefing", True) is not False:
                enabled.add("familybot.briefing.weekend")
            if notifications.get("weekly_summary", True) is not False:
                enabled.add("familybot.briefing.weekly")
            if integration("email"):
                enabled.add("familybot.ukeplan")
        def clock(name: str, fallback: tuple[int, int]) -> tuple[int, int]:
            value = str(notifications.get(name) or f"{fallback[0]:02d}:{fallback[1]:02d}")
            hour, minute = value.split(":", 1)
            return int(hour), int(minute)

        selected = []
        for spec in JOB_SPECS:
            if spec.label not in enabled:
                continue
            if spec.label == "familybot.briefing.weekday":
                hour, minute = clock("weekday_time", (6, 45))
                spec = replace(spec, calendar=tuple((day, hour, minute) for day in range(1, 6)))
            elif spec.label == "familybot.briefing.weekend":
                hour, minute = clock("weekend_time", (8, 0))
                spec = replace(spec, calendar=((0, hour, minute), (6, hour, minute)))
            elif spec.label == "familybot.briefing.weekly":
                hour, minute = clock("weekly_time", (21, 0))
                weekdays = {
                    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
                    "thursday": 4, "friday": 5, "saturday": 6,
                }
                day = weekdays.get(str(notifications.get("weekly_weekday") or "sunday"), 0)
                spec = replace(spec, calendar=((day, hour, minute),))
            selected.append(spec)
        return tuple(selected)
    except RuntimeError:
        return JOB_SPECS


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


def failed_job_is_active(
    spec: JobSpec,
    last_exit: Optional[int],
    finished: Optional[datetime],
    now: datetime,
) -> bool:
    """Return whether a recorded job failure should warn in this snapshot.

    The health job deliberately exits 1 when it observes a warning elsewhere.
    Treating that observation as another scheduler failure creates a recursive
    warning between health runs. Exit 2 and unexpected failures remain active.
    """
    if spec.label == "familybot.health" and last_exit == 1:
        return False
    recent = bool(finished and (now - finished).total_seconds() <= 36 * 3600)
    return spec.kind == "interval" or recent


def latest_calendar_due(spec: JobSpec, now: datetime) -> Optional[datetime]:
    """Return the most recent configured local calendar time not after now."""
    local_zone = schedule_zone()
    local_now = now.astimezone(local_zone)
    for offset in range(0, 8):
        candidate_date = local_now.date() - timedelta(days=offset)
        weekday = (candidate_date.weekday() + 1) % 7
        for configured_day, hour, minute in spec.calendar:
            if configured_day != weekday:
                continue
            candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=local_zone)
            if candidate <= local_now:
                return candidate.astimezone(timezone.utc)
    return None


def next_calendar_due(spec: JobSpec, now: datetime) -> Optional[datetime]:
    local_zone = schedule_zone()
    local_now = now.astimezone(local_zone)
    for offset in range(0, 8):
        candidate_date = local_now.date() + timedelta(days=offset)
        weekday = (candidate_date.weekday() + 1) % 7
        for configured_day, hour, minute in spec.calendar:
            if configured_day != weekday:
                continue
            candidate = datetime.combine(candidate_date, time(hour, minute), tzinfo=local_zone)
            if candidate > local_now:
                return candidate.astimezone(timezone.utc)
    return None


def plist_path(home: Path, label: str) -> Path:
    if label not in JOB_BY_LABEL:
        raise ValueError(f"unknown FamilyBot label: {label}")
    return home / "Library" / "LaunchAgents" / f"{label}.plist"
