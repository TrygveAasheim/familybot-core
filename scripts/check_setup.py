"""Privacy-safe FamilyBot prerequisite and runtime readiness check."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

from database_migrations import CORE_SCHEMA_VERSION, schema_version
from family_config import workspace_path

MINIMUM_PYTHON = (3, 12, 0)
MINIMUM_NODE = (22, 22, 3)
MAXIMUM_NODE_MAJOR = 22
MINIMUM_HIMALAYA = (1, 2, 0)
TESTED_OPENCLAW = "2026.7.1-2"
REQUIRED_CORE_TABLES = {
    "activities",
    "calendar_events",
    "email_log",
    "email_senders",
    "family_members",
    "kanban_cards",
    "norwegian_holidays",
    "routing_audit",
    "school_calendar",
    "school_years",
    "week_plan_days",
    "week_plans",
}


class Check(NamedTuple):
    level: str
    name: str
    detail: str
    remedy: str = ""


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    return tuple(int(part) for part in match.groups()) if match else None


def run_quiet(argv: Sequence[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def command_path(name: str, environment_name: str = "") -> str | None:
    configured = os.environ.get(environment_name, "").strip() if environment_name else ""
    if configured:
        expanded = str(Path(configured).expanduser())
        return expanded if os.access(expanded, os.X_OK) else None
    return shutil.which(name)


def check_command(
    name: str,
    *,
    required: bool = True,
    environment_name: str = "",
    remedy: str = "",
) -> tuple[Check, str | None]:
    path = command_path(name, environment_name)
    if path:
        return Check("PASS", name, f"available at {path}"), path
    level = "FAIL" if required else "WARN"
    scope = "required" if required else "optional for the selected feature set"
    return Check(level, name, f"not found ({scope})", remedy), None


def check_version(
    name: str,
    path: str,
    argv: Sequence[str],
    accepted: Callable[[tuple[int, int, int]], bool],
    expected: str,
    remedy: str,
) -> Check:
    try:
        result = run_quiet([path, *argv])
    except (OSError, subprocess.TimeoutExpired):
        return Check("FAIL", name, "version check could not run", remedy)
    parsed = version_tuple(f"{result.stdout}\n{result.stderr}")
    if result.returncode == 0 and parsed and accepted(parsed):
        return Check("PASS", name, f"version {'.'.join(map(str, parsed))}")
    found = ".".join(map(str, parsed)) if parsed else "unknown"
    return Check("FAIL", name, f"version {found}; expected {expected}", remedy)


def private_file_check(path: Path, name: str) -> Check:
    if not path.is_file():
        return Check("FAIL", name, f"missing: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        return Check("FAIL", name, f"permissions are {mode:04o}; expected 0600", f"chmod 600 {path}")
    return Check("PASS", name, f"present with mode 0600: {path}")


def secret_keys_check(path: Path, keys: set[str], name: str) -> Check:
    file_check = private_file_check(path, name)
    if file_check.level != "PASS":
        return file_check
    try:
        present = {
            line.partition("=")[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }
    except OSError as exc:
        return Check("FAIL", name, f"could not read key names: {type(exc).__name__}")
    missing = sorted(keys - present)
    if missing:
        return Check("FAIL", name, f"missing required key name(s): {', '.join(missing)}")
    return Check("PASS", name, "required key names are present; values were not inspected or printed")


def database_check(path: Path) -> Check:
    if not path.is_file():
        return Check(
            "FAIL",
            "family database",
            f"missing: {path}",
            "Run scripts/manage_database.py init with the validated local family configuration.",
        )
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            version = schema_version(connection)
    except sqlite3.Error as exc:
        return Check("FAIL", "family database", f"could not be opened safely: {type(exc).__name__}")
    if not result or result[0] != "ok":
        return Check("FAIL", "family database", "SQLite integrity check did not return ok")
    missing = sorted(REQUIRED_CORE_TABLES - tables)
    if missing:
        return Check(
            "FAIL",
            "family database",
            f"integrity is ok, but the supported Core schema is missing: {', '.join(missing)}",
            "Run scripts/manage_database.py migrate; it creates a verified backup before changing existing data.",
        )
    if version != CORE_SCHEMA_VERSION:
        return Check(
            "FAIL",
            "family database",
            f"Core schema version is {version}; expected {CORE_SCHEMA_VERSION}",
            "Run scripts/manage_database.py migrate before deploying either repository.",
        )
    return Check("PASS", "family database", f"integrity and Core schema version {version} are ok")


def capability_check(name: str, argv: Sequence[str], remedy: str) -> Check:
    try:
        result = run_quiet(argv, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return Check("FAIL", name, "capability check could not run", remedy)
    if result.returncode == 0:
        return Check("PASS", name, "capability check succeeded")
    return Check("FAIL", name, "capability check failed; command output was intentionally suppressed", remedy)


def integration_is_enabled(config: dict, name: str) -> bool:
    value = config.get("integrations", {}).get(name)
    return isinstance(value, dict) and value.get("enabled", True) is not False


def parent_pin_path(workspace: Path) -> Path:
    return Path(
        os.environ.get("FAMILYBOT_PARENT_PIN_FILE", workspace / "config/parent-pin.txt")
    ).expanduser()


def profile_selection_check(config: dict, selected: str) -> Check:
    configured = config.get("profile", "agent")
    if configured == selected:
        return Check("PASS", "capability profile", f"configuration and check both use {selected}")
    return Check(
        "FAIL",
        "capability profile",
        f"configuration uses {configured}; runtime check selected {selected}",
        f"Rerun with --profile {configured}, or deliberately change and redeploy the configuration.",
    )


def collect_checks(root: Path, mode: str, profile: str = "dashboard") -> list[Check]:
    profile = {"mail": "connected", "full": "agent"}.get(profile, profile)
    checks: list[Check] = []
    workspace = workspace_path()
    config = Path(
        os.environ.get(
            "FAMILYBOT_FAMILY_CONFIG", workspace / "config/family.local.json"
        )
    ).expanduser()
    config_document: dict = {}
    if mode == "runtime" and config.is_file():
        try:
            loaded = json.loads(config.read_text(encoding="utf-8"))
            config_document = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            pass
    if mode == "runtime" and config_document:
        checks.append(profile_selection_check(config_document, profile))
    if platform.system() == "Darwin":
        checks.append(Check("PASS", "macOS", f"host is {platform.mac_ver()[0] or 'macOS'}"))
    else:
        checks.append(Check("FAIL", "macOS", "the appliance deployment currently requires macOS launchd and Bonjour"))

    python_path = str(Path(sys.executable).resolve())
    python_version = tuple(sys.version_info[:3])
    if python_version >= MINIMUM_PYTHON:
        checks.append(Check("PASS", "Python", f"version {platform.python_version()} at {python_path}"))
    else:
        checks.append(Check(
            "FAIL",
            "Python",
            f"version {platform.python_version()} at {python_path}; expected 3.12+",
            "Create the documented uv Python 3.12 environment and rerun this script with its python.",
        ))

    required_commands = {
        "git": "Install Apple's Command Line Tools with xcode-select --install.",
        "brew": "Install Homebrew from https://brew.sh/.",
        "xcode-select": "Install Apple's Command Line Tools with xcode-select --install.",
        "npm": "Install the documented Node.js 22 baseline.",
        "uv": "brew install uv",
        "sqlite3": "brew install sqlite",
        "curl": "curl is supplied by macOS.",
        "rsync": "rsync is supplied by macOS.",
        "dns-sd": "dns-sd is supplied by macOS Bonjour.",
        "launchctl": "launchctl is supplied by macOS.",
    }
    paths: dict[str, str] = {}
    for command, remedy in required_commands.items():
        check, path = check_command(command, remedy=remedy)
        checks.append(check)
        if path:
            paths[command] = path

    node_check, node_path = check_command("node", remedy="Install Node.js 22.22.3 or newer in the 22.x line.")
    checks.append(node_check)
    if node_path:
        checks.append(check_version(
            "Node.js",
            node_path,
            ["--version"],
            lambda value: value >= MINIMUM_NODE and value[0] <= MAXIMUM_NODE_MAJOR,
            "22.22.3 through 22.x",
            "Install the documented Node.js 22 baseline and ensure it is first on PATH.",
        ))

    openclaw_required = mode == "runtime" and profile == "agent"
    openclaw_check, openclaw_path = check_command(
        "openclaw",
        required=openclaw_required,
        environment_name="FAMILYBOT_OPENCLAW",
        remedy=f"npm install --global openclaw@{TESTED_OPENCLAW}",
    )
    checks.append(openclaw_check)
    if openclaw_path:
        try:
            result = run_quiet([openclaw_path, "--version"])
            version_text = (result.stdout or result.stderr).strip().splitlines()[0][:120]
        except (OSError, subprocess.TimeoutExpired):
            version_text = "version unavailable"
        parsed = version_tuple(version_text)
        if parsed and parsed >= (2026, 7, 1):
            checks.append(Check("PASS", "OpenClaw version", version_text or "installed"))
        else:
            checks.append(Check(
                "FAIL" if openclaw_required else "WARN",
                "OpenClaw version",
                f"{version_text or 'unknown'}; tested baseline is {TESTED_OPENCLAW}",
                f"npm install --global openclaw@{TESTED_OPENCLAW}",
            ))

    email_required = (
        mode == "runtime"
        and profile in {"connected", "agent"}
        and integration_is_enabled(config_document, "email")
    )
    himalaya_check, himalaya_path = check_command(
        "himalaya",
        required=email_required,
        remedy="brew install himalaya",
    )
    checks.append(himalaya_check)
    if himalaya_path:
        checks.append(check_version(
            "Himalaya",
            himalaya_path,
            ["--version"],
            lambda value: value >= MINIMUM_HIMALAYA,
            "1.2.0 or newer",
            "brew upgrade himalaya",
        ))

    portal = root.parent / "familybot-portal"
    checks.append(
        Check("PASS", "sibling portal", f"found: {portal}")
        if (portal / "package.json").is_file()
        else Check("FAIL", "sibling portal", f"expected familybot-portal beside Core: {portal}")
    )

    if mode == "runtime":
        checks.append(private_file_check(config, "family configuration"))
        if config.is_file():
            checks.append(capability_check(
                "family configuration validation",
                [sys.executable, str(root / "scripts/validate_config.py"), "--config", str(config)],
                "Correct the fields reported by scripts/validate_config.py; values remain private.",
            ))
            spond_groups = config_document.get("integrations", {}).get("spond", {}).get("groups", [])
            if spond_groups:
                checks.append(secret_keys_check(
                    workspace / "secrets.env",
                    {"SPOND_USERNAME", "SPOND_PASSWORD"},
                    "Spond credential file",
                ))
        checks.append(database_check(Path(os.environ.get("FAMILYBOT_DB_PATH", workspace / "db/family.db")).expanduser()))
        checks.append(private_file_check(parent_pin_path(workspace), "portal parent PIN"))
        if openclaw_path and profile == "agent":
            checks.append(capability_check(
                "OpenClaw gateway",
                [openclaw_path, "gateway", "health"],
                "Run openclaw onboard, then openclaw gateway install and openclaw gateway start.",
            ))
            checks.append(capability_check(
                "OpenClaw model access",
                [openclaw_path, "models", "status"],
                "Run openclaw configure and select an available OpenAI model.",
            ))
            checks.append(capability_check(
                "OpenClaw Telegram channel",
                [openclaw_path, "channels", "status", "--probe"],
                "Run openclaw channels add --channel telegram, then check the bot and parent targets.",
            ))
        if himalaya_path and email_required:
            checks.append(capability_check(
                "Himalaya mailbox",
                [himalaya_path, "folder", "list", "--output", "json"],
                "Run himalaya account configure and verify the dedicated mailbox/app password.",
            ))
    return checks


def print_report(checks: Sequence[Check], mode: str, profile: str = "dashboard") -> int:
    print(f"FamilyBot setup check ({mode}, {profile} profile)")
    print("No configuration values, credentials, mailbox contents, or database rows are printed.\n")
    for check in checks:
        print(f"{check.level:4}  {check.name}: {check.detail}")
        if check.remedy and check.level != "PASS":
            print(f"      Next: {check.remedy}")
    failures = sum(check.level == "FAIL" for check in checks)
    warnings = sum(check.level == "WARN" for check in checks)
    print(f"\nSummary: {failures} failure(s), {warnings} optional warning(s).")
    if mode == "source" and not failures:
        print("Next: follow GETTING_STARTED.md, create private configuration, then run --runtime.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("source", "runtime"),
        default="source",
        help="source checks software/checkouts; runtime also checks private state and live capabilities",
    )
    parser.add_argument(
        "--profile",
        choices=("dashboard", "connected", "agent", "mail", "full"),
        default="dashboard",
        help="dashboard is standalone; connected enables selected adapters; agent adds OpenClaw/Telegram (mail/full are aliases)",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    return print_report(collect_checks(root, args.mode, args.profile), args.mode, args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
