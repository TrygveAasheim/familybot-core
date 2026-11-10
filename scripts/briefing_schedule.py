#!/usr/bin/env python3
"""Audit duplicate Unix cron briefings; retire only exact recognized entries on request."""

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from reliability import atomic_write_text


def read_crontab():
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
    except UnicodeError as exc:
        raise RuntimeError("Cannot decode user crontab safely; no changes made") from exc
    if result.returncode == 1 and "no crontab for" in result.stderr.lower():
        return ""
    if result.returncode:
        raise RuntimeError("Cannot inspect user crontab; no changes made")
    return result.stdout


def retirement_plan(content, workspace):
    """Never evaluate shell text. Preserve unrelated or ambiguous lines byte-for-byte."""
    script = str(workspace / "scripts/briefing.py")
    output = []
    kinds = []
    ambiguous = 0
    for line in content.splitlines(keepends=True):
        if line.lstrip().startswith("#") or script not in line:
            output.append(line)
            continue
        fields = line.split(maxsplit=5)
        try:
            command = shlex.split(fields[5]) if len(fields) == 6 else []
        except ValueError:
            command = []
        recognized = (
            len(fields) == 6 and all(re.fullmatch(r"[0-9*,/\-]+", x) for x in fields[:5])
            and len(command) >= 3
            and re.fullmatch(r"python3(?:\.\d+)?", Path(command[0]).name)
            and (Path(command[0]).is_absolute() or command[0] == "python3")
            and command[1] == script and command[2] in {"daily", "weekly"}
            and command[3:] in ([], [">>", str(workspace / "logs/briefing.log"), "2>&1"])
        )
        if recognized:
            kinds.append(command[2])
            output.append("# FamilyBot retired duplicate: " + line)
        else:
            ambiguous += 1
            output.append(line)
    return "".join(output), kinds, ambiguous


def schedule_health(workspace):
    try:
        _, kinds, ambiguous = retirement_plan(read_crontab(), workspace)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return {"service": "briefing_schedule", "status": "warn",
                "msg": "Unable to audit Unix cron briefing ownership; inspect locally"}
    return {
        "service": "briefing_schedule", "status": "warn" if kinds or ambiguous else "ok",
        "msg": (f"Legacy Unix cron briefings found ({len(kinds)} recognized, {ambiguous} require review); "
                "use briefing_schedule.py audit before retiring duplicates; do not replay briefings"
                if kinds or ambiguous else "No legacy Unix cron briefings found for this workspace"),
    }


def verify_managed_jobs(workspace, kinds):
    labels = set()
    for kind in kinds:
        labels.update(("weekday", "weekend") if kind == "daily" else ("weekly",))
    for suffix in sorted(labels):
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/familybot.briefing.{suffix}"],
            capture_output=True, text=True, timeout=15,
        )
        task = "briefing-weekly" if suffix == "weekly" else "briefing-daily"
        arguments = re.search(r"\barguments = \{\n(.*?)\n\s*\}", result.stdout, re.S)
        argv = [line.strip().strip('"') for line in arguments[1].splitlines()] if arguments else []
        if result.returncode or argv != ["/bin/bash", str(workspace / "scripts/cron_runner.sh"), task]:
            raise RuntimeError("Matching managed briefing jobs must be loaded before retiring cron")


def apply_retirement(workspace, expected_digest):
    original = read_crontab()
    if hashlib.sha256(original.encode()).hexdigest() != expected_digest:
        raise RuntimeError("Crontab changed since audit; audit again before applying")
    updated, kinds, ambiguous = retirement_plan(original, workspace)
    if ambiguous:
        raise RuntimeError("Unrecognized briefing commands require manual review; no changes made")
    if not kinds:
        return None
    verify_managed_jobs(workspace, kinds)
    backup_root = workspace / "backups"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="legacy-briefing-cron-", dir=backup_root)) / "crontab.txt"
    atomic_write_text(backup, original)  # Private, exact recovery copy before installation.
    if read_crontab() != original:
        raise RuntimeError("Crontab changed during preparation; no changes made")
    result = subprocess.run(["crontab", "-"], input=updated, capture_output=True, text=True, timeout=15)
    if result.returncode or read_crontab() != updated:
        raise RuntimeError("Crontab installation not verified; inspect locally using the private backup")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="comment recognized duplicates after private backup")
    parser.add_argument("--expected-sha256", help="digest printed by the preceding read-only audit")
    args = parser.parse_args()
    workspace = args.workspace.expanduser().absolute()
    try:
        if args.apply:
            if not args.expected_sha256:
                parser.error("--apply requires --expected-sha256 from the audit")
            backup = apply_retirement(workspace, args.expected_sha256)
            print(f"Legacy briefing cron retired; private backup: {backup}" if backup else "No recognized entries to retire")
        else:
            content = read_crontab()
            _, kinds, ambiguous = retirement_plan(content, workspace)
            print(f"Recognized legacy entries: {len(kinds)}; require manual review: {ambiguous}")
            print(f"Audit SHA256: {hashlib.sha256(content.encode()).hexdigest()}")
            print("Read-only audit; no schedules, state or messages changed.")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else "Schedule operation failed; inspect locally before retrying")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
