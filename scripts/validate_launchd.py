#!/usr/bin/env python3
"""Validate FamilyBot's source-controlled launchd schedule contract."""

from __future__ import annotations

import argparse
import plistlib
import re
from pathlib import Path
from typing import Any


WORKSPACE_TOKEN = "__FAMILYBOT_WORKSPACE__"


EXPECTED: dict[str, dict[str, Any]] = {
    "familybot.briefing.weekday.plist.example": {
        "label": "familybot.briefing.weekday",
        "task": "briefing-daily",
        "calendar": [(1, 6, 45), (2, 6, 45), (3, 6, 45), (4, 6, 45), (5, 6, 45)],
    },
    "familybot.briefing.weekend.plist.example": {
        "label": "familybot.briefing.weekend",
        "task": "briefing-daily",
        "calendar": [(0, 8, 0), (6, 8, 0)],
    },
    "familybot.briefing.weekly.plist.example": {
        "label": "familybot.briefing.weekly",
        "task": "briefing-weekly",
        "calendar": [(0, 21, 0)],
    },
    "familybot.delivery.plist.example": {
        "label": "familybot.delivery",
        "task": "delivery",
        "interval": 300,
    },
    "familybot.ukeplan.plist.example": {
        "label": "familybot.ukeplan",
        "task": "ukeplan-interpret",
        "interval": 900,
    },
}


def _calendar_entries(value: Any) -> list[tuple[int, int, int]]:
    entries = value if isinstance(value, list) else [value]
    return sorted(
        (
            int(item["Weekday"]),
            int(item["Hour"]),
            int(item["Minute"]),
        )
        for item in entries
    )


def validate_templates(template_dir: Path) -> list[str]:
    errors: list[str] = []
    for filename, expected in EXPECTED.items():
        path = template_dir / filename
        if not path.is_file():
            errors.append(f"missing template: {path}")
            continue
        try:
            document = plistlib.loads(path.read_bytes())
        except Exception as exc:
            errors.append(f"invalid plist {path}: {exc}")
            continue

        if document.get("Label") != expected["label"]:
            errors.append(f"{filename}: unexpected Label")
        arguments = document.get("ProgramArguments", [])
        expected_arguments = [
            "/bin/bash",
            f"{WORKSPACE_TOKEN}/scripts/cron_runner.sh",
            expected["task"],
        ]
        if arguments != expected_arguments:
            errors.append(f"{filename}: ProgramArguments must use the workspace token and task {expected['task']}")
        if document.get("EnvironmentVariables", {}).get("FAMILYBOT_WORKSPACE") != WORKSPACE_TOKEN:
            errors.append(f"{filename}: FAMILYBOT_WORKSPACE must use the workspace token")
        for key in ("StandardOutPath", "StandardErrorPath"):
            if WORKSPACE_TOKEN not in str(document.get(key, "")):
                errors.append(f"{filename}: {key} must stay inside the workspace")

        if "calendar" in expected:
            actual = _calendar_entries(document.get("StartCalendarInterval"))
            if actual != expected["calendar"]:
                errors.append(f"{filename}: unexpected calendar intervals {actual!r}")
        elif document.get("StartInterval") != expected["interval"]:
            errors.append(f"{filename}: StartInterval must be {expected['interval']} seconds")

    return errors


def validate_launchctl_output(label: str, output: str) -> list[str]:
    """Check loaded calendar descriptors against the reviewed contract."""
    expected = EXPECTED.get(f"{label}.plist.example")
    if not expected or "calendar" not in expected:
        return []
    pattern = re.compile(
        r'descriptor = \{\s*'
        r'"Minute" => (\d+)\s*'
        r'"Hour" => (\d+)\s*'
        r'"Weekday" => (\d+)\s*\}',
        re.MULTILINE,
    )
    actual = sorted((int(weekday), int(hour), int(minute)) for minute, hour, weekday in pattern.findall(output))
    expected_calendar = sorted(expected["calendar"])
    if actual != expected_calendar:
        return [f"{label}: loaded calendar intervals are {actual!r}, expected {expected_calendar!r}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--templates",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "ops" / "launchd",
        help="directory containing .plist.example templates",
    )
    args = parser.parse_args()
    errors = validate_templates(args.templates)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"Launchd template validation OK: {len(EXPECTED)} templates checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
