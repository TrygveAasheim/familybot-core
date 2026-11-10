"""Bounded, privacy-safe OpenClaw JSON health contracts; no recovery side effects."""

from __future__ import annotations

import json
from typing import Callable


def _object(value):
    return value if isinstance(value, dict) else {}


def _decode(output):
    try:
        return _object(json.loads(output))
    except (ValueError, TypeError):
        return {}


def gateway_health(code: int, output: str) -> dict:
    result = {"service": "gateway", "status": "warn",
              "msg": "Gateway probe unavailable or unrecognized; inspect CLI/configuration"}
    data = _decode(output)
    rpc = _object(data.get("rpc"))
    if code == 0 and rpc.get("ok") is True:
        return {"service": "gateway", "status": "ok", "msg": "Gateway RPC check OK"}
    if rpc.get("ok") is not False:
        return result
    result.update(status="critical", msg="Gateway RPC check failed; inspect service and authentication")
    service = _object(data.get("service"))
    runtime = _object(service.get("runtime"))
    # A failed authenticated probe alone may be bad credentials/permissions.
    # Restart only a positively observed stopped/unloaded local service.
    if (service.get("targetRole") == "target"
            and (service.get("loaded") is False or runtime.get("status") == "stopped")):
        result.update(msg="Gateway RPC failed and local service is stopped or unloaded",
                      auto_fix="restart", recovery_evidence="service_stopped")
    return result


def telegram_health(code: int, output: str) -> dict:
    result = {"service": "telegram", "status": "warn",
              "msg": "Telegram probe unavailable or unrecognized; inspect channel configuration"}
    data = _decode(output)
    if code != 0:
        return result
    summary = _object(_object(data.get("channels")).get("telegram"))
    accounts = _object(data.get("channelAccounts"))
    if "telegram" in accounts:
        candidates = accounts["telegram"]
        if not isinstance(candidates, list) or any(not isinstance(a, dict) for a in candidates):
            return result
        candidates = [a for a in candidates if a.get("enabled") is not False]
    else:
        # Older CLI versions expose only the channel summary.
        candidates = [summary] if summary else []
    if not candidates:
        return result
    for account in candidates:
        if account.get("enabled") is False or account.get("configured") is not True:
            result["msg"] = "Telegram enabled account is not configured"
            return result
        if account.get("running") is not True or account.get("connected") is False:
            result["msg"] = "Telegram account is not running or is disconnected"
            return result
        if account.get("lastError") or _object(account.get("probe")).get("ok") is not True:
            result["msg"] = "Telegram credential probe failed or is unavailable"
            return result
    return {"service": "telegram", "status": "ok",
            "msg": "Telegram running; enabled account credential probes OK"}


def check_openclaw(openclaw: str, run: Callable) -> list[dict]:
    """Use explicit probe deadlines within the caller's 15-second process bound.

    The channel probe verifies credentials, not recipient delivery. Raw CLI
    output/errors (which can include credentials or paths) never enter alerts.
    """
    code, output, _ = run([openclaw, "gateway", "status", "--json", "--timeout", "8000"])
    gateway = gateway_health(code, output)
    code, output, _ = run([openclaw, "channels", "status", "--probe", "--json", "--timeout", "8000"])
    return [gateway, telegram_health(code, output)]
