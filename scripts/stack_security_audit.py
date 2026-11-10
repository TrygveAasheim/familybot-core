#!/usr/bin/env python3
"""Opt-in, read-only stack inventory and advisory checks. Never upgrades software."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)")
LIMIT = 4 * 1024 * 1024
BINARIES = {"openclaw", "codex", "gateway_node", "portal_node", "core_python",
            "portal_python", "uv", "himalaya", "npm", "pip_audit"}
LATEST = {
    "openclaw": "https://registry.npmjs.org/openclaw/latest",
    "codex": "https://registry.npmjs.org/@openai%2fcodex/latest",
    "uv": "https://api.github.com/repos/astral-sh/uv/releases/latest",
    "himalaya": "https://api.github.com/repos/pimalaya/himalaya/releases/latest",
}
NODE_RELEASES = "https://nodejs.org/dist/index.json"
PYTHON_RELEASES = "https://www.python.org/api/v2/downloads/release/?is_published=true"
PYTHON_LIBS = "import json,sqlite3,ssl; print(json.dumps({'sqlite':sqlite3.sqlite_version,'openssl':ssl.OPENSSL_VERSION}))"
PYTHON_SITE = "import sysconfig; print(sysconfig.get_path('purelib'))"


class CheckError(RuntimeError):
    pass


def command(argv, *, cwd=None):
    """No shell, no raw stderr in reports, bounded duration and parsed output."""
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError("command_unavailable_or_timeout") from exc
    if len(result.stdout) > LIMIT or len(result.stderr) > LIMIT:
        raise CheckError("response_too_large")
    return result.returncode, result.stdout, result.stderr


def fetch(url):
    # URLs are code-owned public metadata endpoints, never household input.
    if url not in {*LATEST.values(), NODE_RELEASES, PYTHON_RELEASES}:
        raise CheckError("endpoint_not_allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "FamilyBot-stack-audit/1"})
    try:
        # B310: only the fixed HTTPS endpoints above are permitted.
        with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310
            payload = response.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise CheckError("response_too_large")
        return json.loads(payload)
    except (OSError, ValueError) as exc:
        raise CheckError("registry_unavailable_or_invalid") from exc


def version(value):
    found = VERSION.search(str(value))
    return found.group(1) if found else None


def newer(current, latest):
    def numeric(value):
        return tuple(int(x) for x in value.split("-")[0].split("."))
    return numeric(latest) > numeric(current)


def sqlite_wal_reset_risk(value):
    """Upstream WAL-reset fix: 3.51.3+, with 3.44.6 and 3.50.7 backports."""
    parts = tuple(int(x) for x in value.split("."))
    if parts[:2] == (3, 44) and parts >= (3, 44, 6):
        return False
    if parts[:2] == (3, 50) and parts >= (3, 50, 7):
        return False
    return (3, 7, 0) <= parts < (3, 51, 3)


def load_config(path):
    if path.stat().st_mode & 0o077:
        raise CheckError("configuration_must_be_owner_only")
    config = json.loads(path.read_text())
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise CheckError("invalid_configuration_version")
    if set(config) - {"schema_version", "workspace", "binaries", "portal_repo"}:
        raise CheckError("unknown_configuration_field")
    binaries = config.get("binaries", {})
    if not isinstance(binaries, dict) or set(binaries) - BINARIES:
        raise CheckError("invalid_binary_allowlist")
    for name, value in {**binaries, "workspace": config.get("workspace"),
                        **({"portal_repo": config["portal_repo"]} if "portal_repo" in config else {})}.items():
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise CheckError("absolute_paths_required")
        if name == "workspace" and Path(value) in (Path("/"), Path.home()):
            raise CheckError("dedicated_workspace_required")
    return config


def audit(config):
    report = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
              "versions": {}, "checks": {}, "limitations": [
                  "No automatic upgrades, model calls, messages, household database reads or credential tests.",
                  "Package advisories do not audit bundled SQLite/OpenSSL, host OS or provider contracts.",
                  "Portal npm audit covers the selected source lock, not proof of the deployed bundle.",
              ]}
    binaries = config.get("binaries", {})

    def check(name, operation):
        try:
            report["checks"][name] = operation()
        except (CheckError, ValueError, TypeError, KeyError, AttributeError):
            report["checks"][name] = {"status": "unavailable"}

    for name, executable in binaries.items():
        def inventory(name=name, executable=executable):
            code, out, err = command([executable, "--version"])
            installed = version(out or err)
            if code or not installed:
                raise CheckError("version_unavailable")
            report["versions"][name] = {"installed": installed}
            return {"status": "ok"}
        check("version_" + name, inventory)

    for name in LATEST.keys() & report["versions"].keys():
        def release(name=name):
            payload = fetch(LATEST[name])
            latest = version(payload.get("version") or payload.get("tag_name"))
            if not latest:
                raise CheckError("release_unavailable")
            entry = report["versions"][name]
            entry.update(latest=latest, update_available=newer(entry["installed"], latest))
            return {"status": "ok"}
        check("release_" + name, release)

    for name in ("gateway_node", "portal_node"):
        if name not in report["versions"]:
            continue
        def node_release(name=name):
            entry = report["versions"][name]
            major = entry["installed"].split(".")[0]
            releases = fetch(NODE_RELEASES)
            candidates = [item for item in releases if re.fullmatch(r"v" + major + r"\.\d+\.\d+", item["version"])]
            if not candidates:
                raise CheckError("release_unavailable")
            latest = max(candidates, key=lambda x: tuple(int(p) for p in x["version"][1:].split(".")))
            entry.update(latest_same_major=latest["version"][1:],
                         update_available=newer(entry["installed"], latest["version"][1:]))
            return {"status": "ok"}
        check("release_" + name, node_release)

    for name in ("core_python", "portal_python"):
        if name not in binaries:
            continue
        if name in report["versions"]:
            def python_release(name=name):
                entry = report["versions"][name]
                minor = ".".join(entry["installed"].split(".")[:2])
                candidates = [version(item["name"]) for item in fetch(PYTHON_RELEASES)
                              if re.fullmatch(r"Python " + re.escape(minor) + r"\.\d+", item["name"])
                              and item.get("is_published") and not item.get("pre_release")]
                if not candidates:
                    raise CheckError("release_unavailable")
                latest = max(candidates, key=lambda x: tuple(int(p) for p in x.split(".")))
                entry.update(latest_same_minor=latest, update_available=newer(entry["installed"], latest))
                return {"status": "ok"}
            check("release_" + name, python_release)
        def libraries(name=name):
            code, out, _ = command([binaries[name], "-c", PYTHON_LIBS])
            payload = json.loads(out)
            if code or not all(version(payload.get(k)) for k in ("sqlite", "openssl")):
                raise CheckError("library_versions_unavailable")
            versions = {k: version(payload[k]) for k in ("sqlite", "openssl")}
            risk = sqlite_wal_reset_risk(versions["sqlite"])
            return {"status": "attention" if risk else "ok", **versions,
                    "known_risks": ["sqlite_wal_reset"] if risk else []}
        check("libraries_" + name, libraries)
        if "pip_audit" not in binaries:
            report["checks"]["advisories_" + name] = {"status": "not_configured"}
            continue
        def python_audit(name=name):
            code, out, _ = command([binaries[name], "-c", PYTHON_SITE])
            site = out.strip()
            if code or not Path(site).is_absolute():
                raise CheckError("site_unavailable")
            code, out, _ = command([binaries["pip_audit"], "--path", site,
                                    "--format", "json", "--progress-spinner", "off"])
            payload = json.loads(out)
            dependencies = payload["dependencies"]
            if code not in (0, 1) or not isinstance(dependencies, list) or not dependencies:
                raise CheckError("audit_unavailable")
            # A skipped distribution is incomplete coverage, not a clean scan.
            skipped = sum("skip_reason" in item for item in dependencies)
            count = sum(len(item.get("vulns", [])) for item in dependencies)
            if code == 1 and not count:
                raise CheckError("audit_incomplete")
            return {"status": "attention" if count else "unavailable" if skipped else "ok",
                    "advisories": count, "packages": len(dependencies), "skipped": skipped}
        check("advisories_" + name, python_audit)

    if "openclaw" in binaries:
        def security():
            code, out, _ = command([binaries["openclaw"], "security", "audit", "--json"])
            counts = json.loads(out)["summary"]
            safe = {key: counts[key] for key in ("critical", "warn", "info")}
            if code not in (0, 1) or any(type(value) is not int or value < 0 for value in safe.values()):
                raise CheckError("audit_invalid")
            return {"status": "attention" if safe["critical"] or safe["warn"] else "ok", **safe}
        check("openclaw_security", security)

    if "portal_repo" in config:
        def npm_audit():
            if "npm" not in binaries or not (Path(config["portal_repo"]) / "package-lock.json").is_file():
                raise CheckError("lock_or_auditor_missing")
            code, out, _ = command([binaries["npm"], "audit", "--json", "--package-lock-only",
                                    "--ignore-scripts", "--registry=https://registry.npmjs.org"],
                                   cwd=config["portal_repo"])
            payload = json.loads(out)
            counts = payload["metadata"]["vulnerabilities"]
            safe = {key: counts[key] for key in ("info", "low", "moderate", "high", "critical", "total")}
            if payload.get("error") or code not in (0, 1) or any(type(value) is not int or value < 0 for value in safe.values()):
                raise CheckError("audit_invalid")
            if code == 1 and not safe["total"]:
                raise CheckError("audit_incomplete")
            return {"status": "attention" if safe["total"] else "ok", **safe}
        check("portal_source_advisories", npm_audit)
    statuses = [item["status"] for item in report["checks"].values()]
    report["status"] = "unavailable" if "unavailable" in statuses or not statuses else "attention" if "attention" in statuses else "ok"
    return report


def save_report(workspace, report):
    directory = Path(workspace) / "memory"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".stack-audit-", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / "stack-security-audit.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_schedule(path, config_path, workspace):
    """Explicit opt-in; write but never load/replace a LaunchAgent automatically."""
    logs = Path(workspace) / "logs"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "Label": "familybot.stack-audit",
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()),
                             "--config", str(config_path.resolve())],
        "StartCalendarInterval": {"Weekday": 0, "Hour": 12, "Minute": 15},
        "RunAtLoad": False, "ProcessType": "Background", "LowPriorityIO": True,
        "Umask": 0o077,
        "StandardOutPath": str(logs / "stack-audit.log"),
        "StandardErrorPath": str(logs / "stack-audit.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    }
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = plistlib.dumps(payload)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--write-launchagent", type=Path,
                        help="Write a new weekly Sunday 12:15 local-time plist; do not run or load it")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.write_launchagent:
            write_schedule(args.write_launchagent, args.config, config["workspace"])
            print("Weekly read-only LaunchAgent written; review and load it explicitly.")
            return 0
        report = audit(config)
        save_report(config["workspace"], report)
    except (OSError, ValueError, CheckError):
        print("Stack audit unavailable: check private configuration, permissions and tools.")
        return 2
    print(f"Stack audit: {report['status']}; {len(report['checks'])} checks. Private report updated.")
    return {"ok": 0, "attention": 1, "unavailable": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
