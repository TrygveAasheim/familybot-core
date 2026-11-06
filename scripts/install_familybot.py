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
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from database_migrations import MigrationError, backup_database, initialize_database, migration_status
from family_config import workspace_path
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


def new_hostname(override: str | None = None) -> str:
    """Use the Mac's existing mDNS name, never create or rename a host alias."""
    if override is not None:
        hostname = override
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/sbin/scutil", "--get", "LocalHostName"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if result.returncode or not result.stdout.strip():
            raise InstallError("Cannot detect the Mac LocalHostName; provide --hostname with a working local hostname")
        hostname = result.stdout.strip() + ".local"
    else:
        hostname = "localhost"  # data-only tests; managed deployment still requires macOS
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
        for label in hostname.split(".")
    ):
        raise InstallError("Hostname must be a DNS name or IPv4 address without a scheme, port or path")
    return hostname.lower()


def set_new_hostname(config: dict[str, Any], hostname: str) -> None:
    portal = config["portal"]
    previous = f"http://{portal['hostname']}:{portal['web_port']}"
    origin = f"http://{hostname}:{portal['web_port']}"
    portal["hostname"] = hostname
    portal["allowed_origins"] = list(dict.fromkeys(
        [origin] + [item for item in portal.get("allowed_origins", []) if item != previous]
    ))


def read_pin(source: Path | None, *, non_interactive: bool, legacy: bool = False) -> str:
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
    minimum = 4 if legacy else 6
    if not re.fullmatch(rf"[0-9]{{{minimum},8}}", value):
        raise InstallError(f"Parent PIN must contain {minimum}–8 digits")
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


def service_probe(hostname: str, api_port: int, web_port: int, *, origin_hostname: str | None = None) -> str:
    origin = f"http://{origin_hostname or hostname}:{web_port}"

    def get(port: int, path: str, token: str = "") -> bytes:
        # Dashboard reads may sequentially wait four seconds each for MET and
        # Entur before returning honest unavailable states. Optional outages
        # must not turn a functioning local installation into a failed probe.
        request_timeout = 10 if path == "/api/dashboard" else 2
        connection = http.client.HTTPConnection(hostname, port, timeout=request_timeout)
        try:
            connection.request("GET", path, headers={"Origin": origin, "X-FamilyBot-Local-Token": token})
            response = connection.getresponse()
            raw = response.read(2_000_001)
            if response.status != 200 or len(raw) > 2_000_000:
                raise InstallError(f"HTTP probe {path} returned an unexpected status or oversized response")
            return raw
        except (OSError, http.client.HTTPException) as exc:
            raise InstallError(f"HTTP probe {path} failed ({type(exc).__name__})") from exc
        finally:
            connection.close()

    health = json.loads(get(api_port, "/api/health"))
    if health.get("service") != "familybot-dashboard-api" or health.get("ok") is not True:
        raise InstallError("Configured API port does not serve a healthy FamilyBot API")
    session = json.loads(get(api_port, "/api/session"))
    if session.get("api") != "familybot-local-v2" or not session.get("token"):
        raise InstallError("FamilyBot session/origin check failed")
    dashboard = json.loads(get(api_port, "/api/dashboard", session["token"]))
    if not isinstance(dashboard.get("children"), list):
        raise InstallError("FamilyBot dashboard contract check failed")
    web = get(web_port, "/").lower()
    if b"<html" not in web or not any(marker in web for marker in (b"familieportalen", b"familybot")):
        raise InstallError("Configured web port does not serve the FamilyBot dashboard")
    return session["token"]


def verify_local_service(api_port: int, web_port: int, hostname: str = "127.0.0.1", *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    error = "service not ready"
    while time.monotonic() < deadline:
        try:
            socket.getaddrinfo(hostname, web_port, type=socket.SOCK_STREAM)
            local_session = service_probe("127.0.0.1", api_port, web_port, origin_hostname=hostname)
            named_session = service_probe(hostname, api_port, web_port)
            if not secrets.compare_digest(local_session, named_session):
                raise InstallError("Hostname resolves to a different FamilyBot instance than this Mac")
            return
        except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError, InstallError) as exc:
            error = str(exc) if isinstance(exc, InstallError) else type(exc).__name__
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise InstallError(
        f"Configured hostname/web/API did not become ready ({error}). "
        "Check local DNS, exact allowed_origins, ports and private service logs. "
        "No iPad/LAN verification has been inferred."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
    )
    parser.add_argument("--portal-repo", type=Path, default=ROOT.parent / "familybot-portal")
    parser.add_argument("--config-source", type=Path)
    parser.add_argument("--parent-pin-source", type=Path)
    parser.add_argument("--portal-runtime", type=Path, help="explicit deployed runtime directory; required for managed upgrades")
    parser.add_argument("--upgrade", action="store_true", help="preserve and upgrade an existing household, without starter seeding")
    parser.add_argument("--writers-stopped", action="store_true",
                        help="confirm all Core/Portal/agent processes that use this database have been stopped")
    parser.add_argument("--replace-school-calendar", action="store_true",
                        help="explicitly replace stored school dates from school.calendar_events")
    parser.add_argument("--demo", action="store_true", help="use the fictional Nordlys household")
    parser.add_argument("--hostname", help="working local DNS name or IPv4 address, new configuration only")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--no-deploy", action="store_true", help="initialize and verify data only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = (args.workspace or workspace_path()).expanduser().resolve()
    portal = args.portal_repo.expanduser().resolve()
    config_path = workspace / "config/family.local.json"
    pin_path = workspace / "config/parent-pin.txt"
    database = workspace / "db/family.db"
    backups = workspace / "backups"
    try:
        existing_database = database.is_file() and database.stat().st_size > 0
        if existing_database and not args.upgrade:
            raise InstallError("Existing database: use --upgrade --writers-stopped after stopping all database users")
        if args.upgrade:
            if args.workspace is None and not (os.environ.get("FAMILYBOT_WORKSPACE") or os.environ.get("OPENCLAW_WORKSPACE")):
                raise InstallError("Upgrade requires an explicit --workspace or workspace environment override")
            if not existing_database or not config_path.is_file():
                raise InstallError("Upgrade requires the existing database and its existing family configuration")
            if not args.writers_stopped:
                raise InstallError("Upgrade requires --writers-stopped; stop all database users first (this flag does not stop them)")
        runtime_override = args.portal_runtime or os.environ.get("FAMILYBOT_PORTAL_RUNTIME")
        if args.upgrade and not args.no_deploy and not runtime_override:
            raise InstallError("Managed upgrade requires --portal-runtime or FAMILYBOT_PORTAL_RUNTIME; retain the installed path")
        runtime = Path(runtime_override or workspace / "runtime/familybot-portal").expanduser().resolve()
        if runtime in (ROOT, portal) or workspace.is_relative_to(runtime):
            raise InstallError("Portal runtime must be a dedicated directory, not a checkout or an ancestor of household state")
        for key, expected in (("FAMILYBOT_FAMILY_CONFIG", config_path), ("FAMILYBOT_DB_PATH", database)):
            if os.environ.get(key) and Path(os.environ[key]).expanduser().resolve() != expected:
                raise InstallError(f"{key} conflicts with --workspace; unset it or select the matching workspace")
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
            if args.hostname:
                raise InstallError("--hostname is only for new configuration; existing hostname/origins were preserved")
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
            if args.hostname or not args.config_source:
                set_new_hostname(config, new_hostname(args.hostname))
            write_private_json(config_path, config)
        report = validate(config_path)
        if report.errors:
            raise InstallError("Configuration is invalid:\n- " + "\n- ".join(report.errors))
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if args.upgrade and not args.no_deploy:
            features = config.get("portal", {}).get("features", {})
            if not all(isinstance(features.get(key), bool) for key in ("oda", "oda_ai", "hellofresh", "hellofresh_account")):
                raise InstallError("Managed upgrade requires explicit oda, oda_ai, hellofresh and hellofresh_account booleans; review optional consent first")
        if args.replace_school_calendar and not isinstance(config.get("school", {}).get("calendar_events"), list):
            raise InstallError("--replace-school-calendar requires an explicit school.calendar_events list")
        if config.get("profile") != "dashboard" and not config_preexisting:
            raise InstallError(
                "This entry point installs the safe dashboard baseline first; enable connected/agent capabilities afterward"
            )
        if config.get("profile") != "dashboard":
            print(
                "Using the existing capability profile for database and Portal upgrade; "
                "Core integration jobs are changed only by an explicit deploy_core.sh run."
            )
        pin_source = args.parent_pin_source
        if pin_source is None and os.environ.get("FAMILYBOT_PARENT_PIN_FILE"):
            pin_source = Path(os.environ["FAMILYBOT_PARENT_PIN_FILE"]).expanduser()
        if pin_path.exists() and pin_source is None:
            pin = pin_path.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"[0-9]{4,8}" if args.upgrade else r"[0-9]{6,8}", pin):
                raise InstallError("Existing parent PIN is invalid; replace the private file manually")
        else:
            pin = read_pin(pin_source, non_interactive=args.non_interactive, legacy=args.upgrade)
        if pin_path.exists() and pin_path.read_text(encoding="utf-8").strip() != pin:
            raise InstallError("Refusing to replace an existing parent PIN with a different value")
        if existing_database:
            # Covers all subsequent schema, member, calendar and Portal changes,
            # even when no component migration happens to be pending.
            backup = backup_database(database, backups, label="pre-upgrade")
            print(f"[pre-upgrade-backup] {backup}", flush=True)
        if not pin_path.exists():
            write_pin(pin_path, pin)
        else:
            pin_path.chmod(0o600)
        initialize_database(database, config_path, backups)
        environment = os.environ.copy()
        environment.update(
            {
                "FAMILYBOT_WORKSPACE": str(workspace),
                "FAMILYBOT_FAMILY_CONFIG": str(config_path),
                "FAMILYBOT_PARENT_PIN_FILE": str(pin_path),
                "FAMILYBOT_DB_PATH": str(database),
                "FAMILYBOT_CONFIG_VALIDATOR": str(ROOT / "scripts/validate_config.py"),
            }
        )
        run([sys.executable, str(ROOT / "scripts/calendar_seed.py")]
            + (["--replace-school-calendar"] if args.replace_school_calendar else []), environment=environment)
        run(
            [
                sys.executable,
                str(portal / "local_api/dashboard_migration.py"),
                "--db",
                str(database),
                "--backup-root",
                str(backups),
            ] + ([] if existing_database else ["--seed"]),
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
        if not branch:
            branch = subprocess.check_output(["git", "-C", str(portal), "rev-parse", "HEAD"], text=True).strip()
        deploy_environment = environment | {
            "FAMILYBOT_DEPLOY_BRANCH": branch,
            "FAMILYBOT_PORTAL_RUNTIME": str(runtime),
            "FAMILYBOT_PYTHON": sys.executable,
            "PATH": f"{Path(sys.executable).parent}:{environment.get('PATH', '')}",
        }
        run(
            ["bash", str(portal / "scripts/deploy-local.sh")],
            environment=deploy_environment,
            cwd=portal,
        )
        settings = config["portal"]
        verify_local_service(int(settings.get("api_port", 8788)), int(settings.get("web_port", 3000)), settings["hostname"])
        print(
            "FamilyBot is ready on "
            f"http://{settings.get('hostname', 'familie.local')}:{int(settings.get('web_port', 3000))}/"
        )
        return 0
    except (InstallError, MigrationError, subprocess.TimeoutExpired) as exc:
        print(f"Installation stopped safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
