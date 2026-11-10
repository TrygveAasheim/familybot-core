#!/usr/bin/env python3
"""Audit or repair FamilyBot's OpenClaw model configuration."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Protocol

DEFAULT_MODEL = "openai/gpt-5.6-sol"
DEFAULT_RETIRED_MODELS = ("openai/gpt-5.5",)
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
JOB_ID = re.compile(r"^[A-Za-z0-9-]+$")


class ConfigurationError(RuntimeError):
    """Raised when OpenClaw configuration cannot be inspected or changed."""


class Client(Protocol):
    def model_config(self) -> Any: ...
    def cron_jobs(self) -> list[dict[str, Any]]: ...
    def set_default_model(self, model: str) -> None: ...
    def clear_job_model(self, job_id: str) -> None: ...
    def restart_gateway(self) -> None: ...


class OpenClawClient:
    def __init__(self, executable: str) -> None:
        self.executable = executable

    def _run(self, *arguments: str, timeout: int = 45) -> str:
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConfigurationError(f"OpenClaw command failed: {exc}") from exc
        if result.returncode != 0:
            summary = ""
            try:
                failure = json.loads(result.stdout)
                error = failure.get("error") if isinstance(failure, dict) else None
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    summary = error["message"]
            except json.JSONDecodeError:
                pass
            if not summary:
                detail = (result.stderr or result.stdout).strip().splitlines()
                summary = detail[-1] if detail else f"exit {result.returncode}"
            raise ConfigurationError(f"OpenClaw command failed: {summary}")
        return result.stdout.strip()

    def _json(self, *arguments: str) -> Any:
        output = self._run(*arguments)
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("OpenClaw returned malformed JSON") from exc

    def model_config(self) -> Any:
        return self._json("config", "get", "agents.defaults.model")

    def plugin_config(self) -> Any:
        try:
            return self._json("config", "get", "plugins", "--json")
        except ConfigurationError as exc:
            # Direct-provider installations need not define any plugins.
            if str(exc).startswith("OpenClaw command failed: Config path not found: plugins."):
                return {}
            raise

    def cron_jobs(self) -> list[dict[str, Any]]:
        payload = self._json(
            "gateway",
            "call",
            "cron.list",
            "--params",
            '{"includeDisabled":true,"limit":200}',
            "--json",
        )
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ConfigurationError("OpenClaw cron listing omitted jobs")
        return [job for job in jobs if isinstance(job, dict)]

    def set_default_model(self, model: str) -> None:
        self._run("models", "set", model)

    def clear_job_model(self, job_id: str) -> None:
        if not JOB_ID.fullmatch(job_id):
            raise ConfigurationError("OpenClaw returned an invalid cron job id")
        self._run("cron", "edit", job_id, "--clear-model")

    def restart_gateway(self) -> None:
        self._run("gateway", "restart", timeout=90)


def primary_model(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("primary"), str):
        return payload["primary"]
    return ""


def audit_codex_runtime(plugins: Any) -> list[str]:
    """Check the local launcher without executing it or exposing config values.

    Remote app servers and disabled plugins have no local executable contract.
    A passing check is not evidence of provider authentication or model access.
    """
    if not isinstance(plugins, dict):
        return ["OpenClaw plugin configuration is unreadable"]
    entries = plugins.get("entries", {})
    if not isinstance(entries, dict):
        return ["OpenClaw plugin entries must be an object"]
    codex = entries.get("codex", {})
    if not isinstance(codex, dict):
        return ["Codex plugin configuration must be an object"]
    if codex.get("enabled") is not True:
        return []
    config = codex.get("config", {})
    if not isinstance(config, dict):
        return ["Codex plugin configuration must be an object"]
    server = config.get("appServer", {})
    if not isinstance(server, dict):
        return ["Codex app-server configuration must be an object"]
    if server.get("transport") == "websocket":
        return []
    command = server.get("command")
    # Unset commands use gateway environment/managed runtime resolution, which
    # cannot be inferred safely from this check's (possibly different) PATH.
    if command is None or (isinstance(command, str) and not command.strip()):
        return []
    if not isinstance(command, str):
        return ["Codex app-server command must be a string"]
    resolved = shutil.which(os.path.expanduser(command.strip()))
    if not resolved:
        return ["Configured Codex app-server command is missing or not executable; "
                "repair plugins.entries.codex.config.appServer.command and run a no-delivery smoke test"]
    return []


def pinned_model(job: dict[str, Any]) -> str:
    payload = job.get("payload")
    if not isinstance(payload, dict) or payload.get("kind") != "agentTurn":
        return ""
    model = payload.get("model")
    return model if isinstance(model, str) else ""


def retired_pins(
    jobs: list[dict[str, Any]], retired_models: set[str]
) -> list[tuple[str, str, str]]:
    pins: list[tuple[str, str, str]] = []
    for job in jobs:
        model = pinned_model(job)
        job_id = job.get("id")
        if model in retired_models and isinstance(job_id, str):
            name = job.get("name")
            pins.append((job_id, name if isinstance(name, str) else job_id, model))
    return pins


def audit(
    model_payload: Any,
    jobs: list[dict[str, Any]],
    expected_model: str,
    retired_models: set[str],
) -> list[str]:
    issues: list[str] = []
    current = primary_model(model_payload)
    if current != expected_model:
        issues.append(
            f"agents.defaults.model is {current or 'unset'}; expected {expected_model}"
        )
    for _job_id, name, model in retired_pins(jobs, retired_models):
        issues.append(f"cron job {name!r} pins retired model {model}")
    return issues


def apply_configuration(
    client: Client,
    expected_model: str,
    retired_models: set[str],
    *,
    restart: bool,
) -> tuple[bool, list[str], list[str]]:
    model_payload = client.model_config()
    jobs = client.cron_jobs()
    changed_default = primary_model(model_payload) != expected_model
    pins = retired_pins(jobs, retired_models)

    if changed_default:
        client.set_default_model(expected_model)
    for job_id, _name, _model in pins:
        client.clear_job_model(job_id)
    if restart and (changed_default or pins):
        client.restart_gateway()

    issues = audit(
        client.model_config(), client.cron_jobs(), expected_model, retired_models
    )
    return changed_default, [name for _job_id, name, _model in pins], issues


def parse_retired_models() -> set[str]:
    configured = os.environ.get("FAMILYBOT_RETIRED_OPENCLAW_MODELS")
    values = configured.split(",") if configured else DEFAULT_RETIRED_MODELS
    models = {value.strip() for value in values if value.strip()}
    invalid = sorted(model for model in models if not MODEL_ID.fullmatch(model))
    if invalid:
        raise ConfigurationError("Invalid retired OpenClaw model id")
    return models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Audit only (default)")
    mode.add_argument("--apply", action="store_true", help="Repair the default and retired cron pins")
    parser.add_argument(
        "--model",
        default=os.environ.get("FAMILYBOT_OPENCLAW_MODEL", DEFAULT_MODEL),
        help="Expected provider/model id",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart the gateway after applying changes",
    )
    args = parser.parse_args()
    if args.restart and not args.apply:
        parser.error("--restart requires --apply")
    if not MODEL_ID.fullmatch(args.model):
        parser.error("--model must be a provider/model id")

    executable = shutil.which("openclaw")
    if not executable:
        print("OpenClaw is not installed; model configuration check skipped.")
        return 0

    try:
        retired_models = parse_retired_models()
        client = OpenClawClient(executable)
        if args.apply:
            changed, cleared, issues = apply_configuration(
                client, args.model, retired_models, restart=args.restart
            )
            if changed:
                print(f"Set OpenClaw default model to {args.model}.")
            if cleared:
                print(f"Cleared retired model overrides from {len(cleared)} cron job(s).")
            if not changed and not cleared:
                print("OpenClaw model configuration already matched the expected state.")
        else:
            issues = audit(
                client.model_config(), client.cron_jobs(), args.model, retired_models
            )
        issues.extend(audit_codex_runtime(client.plugin_config()))
        if issues:
            for issue in issues:
                print(f"ERROR: {issue}", file=sys.stderr)
            return 1
        print(f"OpenClaw model configuration OK: {args.model}.")
        return 0
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
