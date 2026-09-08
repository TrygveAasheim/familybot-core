#!/usr/bin/env python3
"""Persist a small, privacy-safe execution record for one scheduled task."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from reliability import atomic_write_json, workspace_path


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def state_path(job: str) -> Path:
    if not job or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in job):
        raise ValueError("invalid job name")
    return workspace_path() / "db" / "job_state" / f"{job}.json"


def read_state(job: str) -> dict:
    path = state_path(job)
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def write_state(job: str, payload: dict) -> None:
    path = state_path(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    os.chmod(path, 0o600)


def start(job: str, pid: int) -> None:
    started = now()
    previous = read_state(job)
    write_state(
        job,
        {
            "job": job,
            "pid": pid,
            "status": "running",
            "started_at": iso(started),
            "finished_at": previous.get("finished_at"),
            "last_exit_code": previous.get("last_exit_code"),
            "duration_seconds": None,
        },
    )


def finish(job: str, pid: int, exit_code: int) -> None:
    finished = now()
    previous = read_state(job)
    started_text = previous.get("started_at")
    duration = None
    if started_text:
        try:
            started = datetime.fromisoformat(started_text)
            duration = max(0.0, (finished - started).total_seconds())
        except ValueError:
            duration = None
    write_state(
        job,
        {
            "job": job,
            "pid": pid,
            "status": "success" if exit_code == 0 else "failed",
            "started_at": started_text,
            "finished_at": iso(finished),
            "last_exit_code": int(exit_code),
            "duration_seconds": duration,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "finish"):
        subparser = subparsers.add_parser(action)
        subparser.add_argument("task")
        subparser.add_argument("pid", type=int)
        if action == "finish":
            subparser.add_argument("exit_code", type=int)
    args = parser.parse_args()
    try:
        if args.action == "start":
            start(args.task, args.pid)
        else:
            finish(args.task, args.pid, args.exit_code)
    except (OSError, ValueError) as exc:
        print(f"job state update failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
