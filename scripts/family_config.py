#!/usr/bin/env python3
"""Family identity and integration settings from a git-ignored local file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def workspace_path() -> Path:
    configured = os.environ.get("FAMILYBOT_WORKSPACE") or os.environ.get("OPENCLAW_WORKSPACE")
    return Path(configured).expanduser() if configured else Path.home() / ".openclaw/workspace"


def config_path() -> Path:
    configured = os.environ.get("FAMILYBOT_FAMILY_CONFIG")
    return Path(configured).expanduser() if configured else workspace_path() / "config/family.local.json"


def load_family_config() -> dict[str, Any]:
    path = config_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Missing or invalid local family configuration: {path}. "
            "Start from config/family.example.json."
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("members"), list):
        raise RuntimeError(f"Family configuration has no members list: {path}")
    return value


def members(role: str | None = None) -> list[dict[str, Any]]:
    result = [item for item in load_family_config()["members"] if isinstance(item, dict)]
    return [item for item in result if item.get("role") == role] if role else result


def member_names() -> dict[int, str]:
    return {int(item["member_id"]): str(item["name"]) for item in members()}


def parents() -> list[dict[str, Any]]:
    return members("parent")


def children() -> list[dict[str, Any]]:
    return members("child")


def telegram_recipients() -> list[tuple[str, str]]:
    return [
        (str(item["name"]), str(item["telegram_target"]))
        for item in parents() if item.get("telegram_target")
    ]


def integration(name: str) -> dict[str, Any]:
    value = load_family_config().get("integrations", {}).get(name, {})
    return value if isinstance(value, dict) else {}


def family_prompt_context() -> str:
    family = load_family_config().get("family", {})
    display_name = family.get("display_name") or "den konfigurerte familien"
    descriptions = []
    for item in members():
        role = "forelder" if item.get("role") == "parent" else "barn"
        suffix = f", {item['age']} år" if item.get("age") else ""
        descriptions.append(f"{item.get('name')} ({role}{suffix})")
    return f"familien {display_name}: " + ", ".join(descriptions)
