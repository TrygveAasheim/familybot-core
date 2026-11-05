#!/usr/bin/env python3
"""Guided, repeatable FamilyBot dashboard installation for a new household."""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from database_migrations import MigrationError, initialize_database, migration_status
from validate_config import validate

ROOT = Path(__file__).resolve().parents[1]


class InstallError(RuntimeError):
    """A user-actionable installation failure."""


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def slug(value: str, used: set[str]) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_") or "member"
    if not candidate[0].isalpha():
        candidate = f"member_{candidate}"
    base = candidate[:56]
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def ask_text(prompt: str, *, default: str = "", required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip() or default
        if value or not required:
            return value
        print("Skriv inn en verdi.")


def ask_count(prompt: str, *, default: int, minimum: int = 0) -> int:
    while True:
        raw = ask_text(prompt, default=str(default))
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if minimum <= value <= 20:
            return value
        print(f"Bruk et heltall mellom {minimum} og 20.")


def interactive_dashboard_config() -> dict[str, Any]:
    print("\nFamilyBot – nytt dashboard\nIngen eksterne integrasjoner aktiveres nå.\n")
    display_name = ask_text("Navn på familien", default="Familien Nordmann")
    members: list[dict[str, Any]] = []
    used: set[str] = set()
    next_id = 1
    for index in range(ask_count("Antall foreldre", default=2, minimum=1)):
        name = ask_text(f"Navn på forelder {index + 1}")
        members.append({"member_id": next_id, "role": "parent", "name": name, "slug": slug(name, used)})
        next_id += 1
    for index in range(ask_count("Antall barn", default=2)):
        name = ask_text(f"Navn på barn {index + 1}")
        school = ask_text("Skole (kan stå tom)", required=False)
        grade = ask_text("Klasse (kan stå tom)", required=False)
        avatar = ask_text("Emoji", default="⭐")
        member: dict[str, Any] = {
            "member_id": next_id,
            "role": "child",
            "name": name,
            "slug": slug(name, used),
            "avatar": avatar,
            "default_reward": {
                "title": "Familiebelønning",
                "emoji": "🎯",
                "target_value": 30,
                "goal_type": "points",
                "unit_label": "poeng",
            },
        }
        if grade:
            member["grade"] = grade
        if school:
            member["school"] = school
        members.append(member)
        next_id += 1
    return {
        "schema_version": 1,
        "profile": "dashboard",
        "family": {
            "display_name": display_name,
            "locale": "nb-NO",
            "timezone": "Europe/Oslo",
        },
        "portal": {
            "hostname": "familie.local",
            "web_port": 3000,
            "api_port": 8788,
            "bonjour_name": "Familieportalen",
            "allowed_origins": [
                "http://familie.local:3000",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
            "features": {
                "oda": False,
                "oda_ai": False,
                "hellofresh": False,
                "hellofresh_account": False,
            },
        },
        "members": members,
        "integrations": {},
    }


def read_pin(source: Path | None, *, non_interactive: bool) -> str:
    if source:
        try:
            value = source.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise InstallError("Could not read the parent PIN source file") from exc
    elif non_interactive:
        raise InstallError("Non-interactive installation requires --parent-pin-source")
    else:
        first = getpass.getpass("Velg foreldrekode (6–8 siffer): ").strip()
        second = getpass.getpass("Gjenta foreldrekoden: ").strip()
        if first != second:
            raise InstallError("Parent PIN entries did not match")
        value = first
    if not re.fullmatch(r"\d{6,8}", value):
        raise InstallError("Parent PIN must contain 6–8 digits")
    return value


def write_pin(path: Path, value: str) -> None:
    private_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, f"{value}\n".encode())
    finally:
        os.close(descriptor)
    path.chmod(0o600)


def run(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    result = subprocess.run(command, env=environment, cwd=cwd, check=False)
    if result.returncode:
        raise InstallError(f"Command failed with exit code {result.returncode}: {command[0]}")


def require_command(name: str, remedy: str) -> str:
    path = shutil.which(name)
    if not path:
        raise InstallError(f"Missing {name}. {remedy}")
    return path


def node_version(node: str) -> tuple[int, int, int]:
    result = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    if result.returncode or not match:
        raise InstallError("Could not determine the installed Node.js version")
    return tuple(int(part) for part in match.groups())


def deployment_dependencies() -> None:
    """Validate the managed macOS deployment toolchain before changing state."""
    if sys.platform != "darwin":
        raise InstallError("Managed LAN deployment currently requires macOS")
    if sys.version_info < (3, 12):
        raise InstallError("Python 3.12 or newer is required; run the installer with uv run --python 3.12")
    node = require_command("node", "Install the documented Node.js 22 baseline.")
    installed_node = node_version(node)
    if installed_node < (22, 22, 3) or installed_node[0] != 22:
        raise InstallError(
            f"Node.js 22.22.3 through 22.x is required; found {'.'.join(map(str, installed_node))}"
        )
    require_command("npm", "Install the documented Node.js 22 baseline.")
    require_command("uv", "Run: brew install uv")
    require_command("git", "Install the macOS Command Line Tools with: xcode-select --install")
    require_command("sqlite3", "sqlite3 is supplied by macOS.")
    require_command("rsync", "rsync is supplied by macOS.")
    require_command("launchctl", "launchctl is supplied by macOS.")
    require_command("dns-sd", "dns-sd is supplied by macOS Bonjour.")


def verify_local_service(api_port: int, web_port: int) -> None:
    deadline = time.monotonic() + 30
    pending = {
        (api_port, "/api/health"): "API",
        (web_port, "/"): "dashboard",
    }
    while pending and time.monotonic() < deadline:
        for port, path in list(pending):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                if 200 <= response.status < 400:
                    pending.pop((port, path))
            except OSError:
                pass
            finally:
                connection.close()
        if pending:
            time.sleep(1)
    if pending:
        raise InstallError(f"Local service did not become ready: {', '.join(pending.values())}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(os.environ.get("FAMILYBOT_WORKSPACE", Path.home() / ".familybot")),
    )
    parser.add_argument("--portal-repo", type=Path, default=ROOT.parent / "familybot-portal")
    parser.add_argument("--config-source", type=Path)
    parser.add_argument("--parent-pin-source", type=Path)
    parser.add_argument("--demo", action="store_true", help="use the fictional Nordlys household")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--no-deploy", action="store_true", help="initialize and verify data only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.expanduser().resolve()
    portal = args.portal_repo.expanduser().resolve()
    config_path = workspace / "config/family.local.json"
    pin_path = workspace / "config/parent-pin.txt"
    database = workspace / "db/family.db"
    backups = workspace / "backups"
    try:
        if not (portal / "local_api/dashboard_migration.py").is_file():
            raise InstallError(f"Portal checkout not found beside Core: {portal}")
        if not args.no_deploy:
            deployment_dependencies()
        for directory in (
            workspace,
            workspace / "config",
            workspace / "db",
            backups,
            workspace / "logs",
            workspace / "runtime",
        ):
            private_directory(directory)
        config_preexisting = config_path.exists()
        if config_preexisting:
            print(f"Using existing private configuration: {config_path}")
        else:
            if args.config_source:
                try:
                    config = json.loads(args.config_source.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise InstallError("Could not read --config-source") from exc
            elif args.demo:
                config = json.loads((ROOT / "config/family.demo.json").read_text(encoding="utf-8"))
            elif args.non_interactive:
                raise InstallError("Non-interactive installation requires --demo or --config-source")
            else:
                config = interactive_dashboard_config()
            write_private_json(config_path, config)
        report = validate(config_path)
        if report.errors:
            raise InstallError("Configuration is invalid:\n- " + "\n- ".join(report.errors))
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("profile") != "dashboard" and not config_preexisting:
            raise InstallError(
                "This entry point installs the safe dashboard baseline first; enable connected/agent capabilities afterward"
            )
        if config.get("profile") != "dashboard":
            print(
                "Using the existing capability profile for database and Portal upgrade; "
                "Core integration jobs are changed only by an explicit deploy_core.sh run."
            )
        if pin_path.exists() and args.parent_pin_source is None:
            pin = pin_path.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"\d{6,8}", pin):
                raise InstallError("Existing parent PIN is invalid; replace the private file manually")
        else:
            pin = read_pin(args.parent_pin_source, non_interactive=args.non_interactive)
        if pin_path.exists() and pin_path.read_text(encoding="utf-8").strip() != pin:
            raise InstallError("Refusing to replace an existing parent PIN with a different value")
        write_pin(pin_path, pin)
        initialize_database(database, config_path, backups)
        environment = os.environ.copy()
        environment.update(
            {
                "FAMILYBOT_WORKSPACE": str(workspace),
                "FAMILYBOT_FAMILY_CONFIG": str(config_path),
                "FAMILYBOT_PARENT_PIN_FILE": str(pin_path),
            }
        )
        run([sys.executable, str(ROOT / "scripts/calendar_seed.py")], environment=environment)
        run(
            [
                sys.executable,
                str(portal / "local_api/dashboard_migration.py"),
                "--db",
                str(database),
                "--backup-root",
                str(backups),
                "--seed",
            ],
            environment=environment,
        )
        run(
            [
                sys.executable,
                str(portal / "local_api/dashboard_migration.py"),
                "--db",
                str(database),
                "--status",
            ],
            environment=environment,
        )
        status = migration_status(database)
        if not status["current"]:
            raise InstallError("Core database did not reach the current schema version")
        if args.no_deploy:
            print(f"Dashboard data initialized and verified. Deployment was skipped by request. Workspace: {workspace}")
            return 0
        run(["npm", "ci"], environment=environment, cwd=portal)
        branch = subprocess.run(
            ["git", "-C", str(portal), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        deploy_environment = environment | {
            "FAMILYBOT_DEPLOY_BRANCH": branch,
            "FAMILYBOT_PORTAL_RUNTIME": str(workspace / "runtime/familybot-portal"),
            "FAMILYBOT_PYTHON": sys.executable,
            "PATH": f"{Path(sys.executable).parent}:{environment.get('PATH', '')}",
        }
        run(
            ["bash", str(portal / "scripts/deploy-local.sh")],
            environment=deploy_environment,
            cwd=portal,
        )
        settings = config["portal"]
        verify_local_service(int(settings.get("api_port", 8788)), int(settings.get("web_port", 3000)))
        print(
            "FamilyBot is ready on "
            f"http://{settings.get('hostname', 'familie.local')}:{int(settings.get('web_port', 3000))}/"
        )
        return 0
    except (InstallError, MigrationError) as exc:
        print(f"Installation stopped safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
