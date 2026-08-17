#!/usr/bin/env python3
"""Fail-fast, privacy-safe validation for FamilyBot's canonical local config."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PLACEHOLDER = re.compile(
    r"(?:^|[^a-z])(?:FAMILY_|PARENT_|CHILD_|SPOND_|FORWARDING_|LOCAL_|HOME_|ENTUR_|TRANSIT_|DIRECTION_|GROUP_|OPTIONAL_|CONTACT_EMAIL)",
)
SLUG = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ROLES = {"parent", "child"}
GOAL_TYPES = {"points", "currency", "items"}
TRANSPORT_MODES = {"metro", "bus", "tram", "rail", "water"}
SECRET_KEY = re.compile(r"(?:^|_)(?:password|passwd|secret|token|api_key|apikey|private_key|client_secret|bot_token)(?:$|_)", re.IGNORECASE)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def warn(self, path: str, message: str) -> None:
        self.warnings.append(f"{path}: {message}")


def default_config_path() -> Path:
    configured = os.environ.get("FAMILYBOT_FAMILY_CONFIG")
    workspace = os.environ.get("FAMILYBOT_WORKSPACE") or os.environ.get("OPENCLAW_WORKSPACE")
    if configured:
        return Path(configured).expanduser()
    return Path(workspace).expanduser() / "config/family.local.json" if workspace else Path.home() / ".openclaw/workspace/config/family.local.json"


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER.search(value))


def require_dict(report: Report, value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        report.error(path, "must be an object")
        return {}
    return value


def require_text(report: Report, value: Any, path: str, *, placeholders: bool, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip():
        report.error(path, "must be a non-empty string")
        return ""
    value = value.strip()
    if len(value) > maximum:
        report.error(path, f"must be at most {maximum} characters")
    if not placeholders and is_placeholder(value):
        report.error(path, "still contains a template placeholder")
    return value


def optional_number(report: Report, value: Any, path: str, minimum: float, maximum: float, *, placeholders: bool) -> float | None:
    if value is None or value == "":
        return None
    if placeholders and is_placeholder(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        report.error(path, "must be numeric")
        return None
    if not minimum <= number <= maximum:
        report.error(path, f"must be between {minimum:g} and {maximum:g}")
    return number


def validate_members(report: Report, members: Any, *, placeholders: bool) -> tuple[set[int], int, int]:
    if not isinstance(members, list) or not members:
        report.error("members", "must be a non-empty array")
        return set(), 0, 0
    ids: set[int] = set()
    slugs: set[str] = set()
    parents = children = 0
    for index, raw in enumerate(members):
        path = f"members[{index}]"
        member = require_dict(report, raw, path)
        try:
            member_id = int(member.get("member_id"))
            if member_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            report.error(f"{path}.member_id", "must be a positive integer")
            continue
        if member_id in ids:
            report.error(f"{path}.member_id", "must be unique")
        ids.add(member_id)
        role = member.get("role")
        if role not in ROLES:
            report.error(f"{path}.role", "must be parent or child")
        elif role == "parent":
            parents += 1
        else:
            children += 1
        require_text(report, member.get("name"), f"{path}.name", placeholders=placeholders, maximum=80)
        slug = require_text(report, member.get("slug"), f"{path}.slug", placeholders=placeholders, maximum=64)
        if slug and not SLUG.fullmatch(slug):
            report.error(f"{path}.slug", "must be a stable lowercase key")
        if slug in slugs:
            report.error(f"{path}.slug", "must be unique")
        slugs.add(slug)
        if role == "child":
            if "grade" not in member:
                report.warn(f"{path}.grade", "missing; school-message routing will be weaker")
            reward = member.get("default_reward")
            if reward is not None:
                reward = require_dict(report, reward, f"{path}.default_reward")
                require_text(report, reward.get("title"), f"{path}.default_reward.title", placeholders=placeholders, maximum=80)
                if reward.get("goal_type", "points") not in GOAL_TYPES:
                    report.error(f"{path}.default_reward.goal_type", "must be points, currency, or items")
                try:
                    target = int(reward.get("target_value"))
                    if not 1 <= target <= 1_000_000:
                        raise ValueError
                except (TypeError, ValueError):
                    report.error(f"{path}.default_reward.target_value", "must be an integer from 1 to 1000000")
    if not parents:
        report.error("members", "must contain at least one parent")
    if not children:
        report.warn("members", "contains no child; child dashboard features will be empty")
    return ids, parents, children


def validate_portal(report: Report, portal_raw: Any, *, placeholders: bool) -> None:
    portal = require_dict(report, portal_raw, "portal")
    hostname = require_text(report, portal.get("hostname"), "portal.hostname", placeholders=placeholders, maximum=253)
    for field, default in (("web_port", 3000), ("api_port", 8788)):
        try:
            port = int(portal.get(field, default))
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            report.error(f"portal.{field}", "must be a TCP port from 1 to 65535")
    require_text(report, portal.get("bonjour_name"), "portal.bonjour_name", placeholders=placeholders, maximum=63)
    origins = portal.get("allowed_origins")
    if not isinstance(origins, list) or not origins:
        report.error("portal.allowed_origins", "must be a non-empty array of exact HTTP origins")
        return
    expected_port = int(portal.get("web_port", 3000)) if str(portal.get("web_port", 3000)).isdigit() else 3000
    normalized: set[str] = set()
    for index, origin in enumerate(origins):
        path = f"portal.allowed_origins[{index}]"
        text = require_text(report, origin, path, placeholders=placeholders, maximum=300)
        try:
            parsed = urlparse(text)
            valid = parsed.scheme == "http" and bool(parsed.hostname) and parsed.port == expected_port and not parsed.path and not parsed.query and not parsed.fragment
        except ValueError:
            valid = False
        if text and not valid:
            report.error(path, f"must be an exact http origin on port {expected_port}")
        if text in normalized:
            report.error(path, "must be unique")
        normalized.add(text)
    if hostname and f"http://{hostname}:{expected_port}" not in normalized:
        report.error("portal.allowed_origins", "must include the configured portal hostname")


def validate_integrations(report: Report, raw: Any, member_ids: set[int], *, placeholders: bool) -> None:
    integrations = require_dict(report, raw, "integrations")
    email = integrations.get("email")
    if email is not None:
        email = require_dict(report, email, "integrations.email")
        require_text(report, email.get("account"), "integrations.email.account", placeholders=placeholders)
        addresses = email.get("forward_addresses", [])
        if not isinstance(addresses, list):
            report.error("integrations.email.forward_addresses", "must be an array")
        else:
            for index, address in enumerate(addresses):
                text = require_text(report, address, f"integrations.email.forward_addresses[{index}]", placeholders=placeholders)
                if text and not placeholders and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
                    report.error(f"integrations.email.forward_addresses[{index}]", "must be an email address")
    spond = integrations.get("spond")
    if spond is not None:
        spond = require_dict(report, spond, "integrations.spond")
        groups = spond.get("groups", [])
        if not isinstance(groups, list):
            report.error("integrations.spond.groups", "must be an array")
        else:
            seen: set[str] = set()
            for index, raw_group in enumerate(groups):
                path = f"integrations.spond.groups[{index}]"
                group = require_dict(report, raw_group, path)
                group_id = require_text(report, group.get("group_id"), f"{path}.group_id", placeholders=placeholders)
                require_text(report, group.get("name"), f"{path}.name", placeholders=placeholders)
                if group_id in seen:
                    report.error(f"{path}.group_id", "must be unique")
                seen.add(group_id)
                owner_value = group.get("member_id")
                try:
                    owner = int(owner_value) if owner_value is not None else None
                except (TypeError, ValueError):
                    owner = -1
                if owner is not None and owner not in member_ids:
                    report.error(f"{path}.member_id", "must reference an existing member_id")
    transport = require_dict(report, integrations.get("transport"), "integrations.transport")
    for field in ("stop_name", "stop_id", "line", "direction_label", "client_name"):
        require_text(report, transport.get(field), f"integrations.transport.{field}", placeholders=placeholders)
    mode = transport.get("transport_mode", "metro")
    if mode not in TRANSPORT_MODES:
        report.error("integrations.transport.transport_mode", "must be metro, bus, tram, rail, or water")
    quay = transport.get("direction_quay_id") or transport.get("centre_quay_id")
    require_text(report, quay, "integrations.transport.direction_quay_id", placeholders=placeholders)
    if transport.get("stop_id") and not placeholders and not str(transport["stop_id"]).startswith("NSR:StopPlace:"):
        report.warn("integrations.transport.stop_id", "does not look like an Entur StopPlace ID")
    if quay and not placeholders and not str(quay).startswith("NSR:Quay:"):
        report.warn("integrations.transport.direction_quay_id", "does not look like an Entur Quay ID")
    weather = require_dict(report, integrations.get("weather"), "integrations.weather")
    user_agent = require_text(report, weather.get("user_agent"), "integrations.weather.user_agent", placeholders=placeholders)
    if user_agent and not placeholders and "@" not in user_agent:
        report.warn("integrations.weather.user_agent", "MET recommends an identifiable user agent with contact information")
    optional_number(report, weather.get("home_lat"), "integrations.weather.home_lat", -90, 90, placeholders=placeholders)
    optional_number(report, weather.get("home_lon"), "integrations.weather.home_lon", -180, 180, placeholders=placeholders)
    cabin_values = [weather.get(name) for name in ("cabin_label", "cabin_lat", "cabin_lon")]
    present = [value not in (None, "") and not (placeholders and is_placeholder(value)) for value in cabin_values]
    if any(present) and not all(present):
        report.error("integrations.weather", "cabin_label, cabin_lat, and cabin_lon must be supplied together or removed")
    if all(present):
        optional_number(report, cabin_values[1], "integrations.weather.cabin_lat", -90, 90, placeholders=placeholders)
        optional_number(report, cabin_values[2], "integrations.weather.cabin_lon", -180, 180, placeholders=placeholders)


def reject_secret_fields(report: Report, value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SECRET_KEY.search(str(key)):
                report.error(child_path, "credential-like fields do not belong in family configuration")
            reject_secret_fields(report, child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_fields(report, child, f"{path}[{index}]")


def validate(path: Path, *, allow_placeholders: bool = False, check_permissions: bool = True) -> Report:
    report = Report()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        report.error("config", f"file is unavailable: {path}")
        return report
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.error("config", f"invalid JSON at line {exc.lineno}, column {exc.colno}")
        return report
    config = require_dict(report, value, "config")
    reject_secret_fields(report, config)
    if config.get("schema_version") != 1:
        report.error("schema_version", "must be 1")
    family = require_dict(report, config.get("family"), "family")
    require_text(report, family.get("display_name"), "family.display_name", placeholders=allow_placeholders, maximum=100)
    require_text(report, family.get("locale"), "family.locale", placeholders=allow_placeholders, maximum=20)
    timezone = require_text(report, family.get("timezone"), "family.timezone", placeholders=allow_placeholders, maximum=100)
    if timezone and not allow_placeholders:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            report.error("family.timezone", "must be an installed IANA timezone")
    member_ids, _, _ = validate_members(report, config.get("members"), placeholders=allow_placeholders)
    validate_portal(report, config.get("portal"), placeholders=allow_placeholders)
    validate_integrations(report, config.get("integrations"), member_ids, placeholders=allow_placeholders)
    if check_permissions:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            report.error("config", f"permissions are {oct(mode)}; use 0o600")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FamilyBot's canonical local configuration without printing its values")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--allow-placeholders", action="store_true", help="validate the shipped template itself")
    parser.add_argument("--skip-permissions", action="store_true", help="skip owner-only file-mode validation")
    args = parser.parse_args()
    report = validate(args.config.expanduser(), allow_placeholders=args.allow_placeholders, check_permissions=not args.skip_permissions)
    for warning in report.warnings:
        print(f"WARN  {warning}")
    for error in report.errors:
        print(f"ERROR {error}")
    if report.errors:
        print(f"Configuration preflight FAILED ({len(report.errors)} error(s), {len(report.warnings)} warning(s)).")
        return 1
    print(f"Configuration preflight OK ({len(report.warnings)} warning(s)); no values were printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
