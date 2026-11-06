#!/usr/bin/env python3
"""Validate the repository's cold-start documentation contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote

REQUIRED_FILES = {
    "AGENTS.md",
    "README.md",
    "ARCHITECTURE.md",
    "CONFIGURATION.md",
    "CREDENTIALS.md",
    "GETTING_STARTED.md",
    "REDEPLOY.md",
    "SECURITY.md",
    "docs/BRANCHES.md",
    "docs/CHANGE_PROTOCOL.md",
    "docs/NEW_SESSION_VERIFICATION.md",
    "docs/REPOSITORY_GUIDE.md",
    "specs/CONSTRAINTS.md",
    "specs/RELIABILITY.md",
    "specs/ROADMAP.md",
    "specs/SMART_HOME.md",
    "specs/VISION.md",
}

REQUIRED_README_LINKS = {
    "GETTING_STARTED.md",
    "docs/REPOSITORY_GUIDE.md",
    "docs/NEW_SESSION_VERIFICATION.md",
    "specs/SMART_HOME.md",
}

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_files(root: Path) -> list[Path]:
    excluded = {".git", ".venv", "node_modules"}
    return sorted(path for path in root.rglob("*.md") if excluded.isdisjoint(path.parts))


def local_link_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    return (document.parent / target).resolve()


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []

    for relative in sorted(REQUIRED_FILES):
        if not (root / relative).is_file():
            errors.append(f"missing required documentation: {relative}")

    readme = root / "README.md"
    if readme.is_file():
        content = readme.read_text(encoding="utf-8")
        for required_link in sorted(REQUIRED_README_LINKS):
            if required_link not in content:
                errors.append(f"README does not link to {required_link}")

    getting_started = root / "GETTING_STARTED.md"
    if getting_started.is_file():
        content = getting_started.read_text(encoding="utf-8")
        required_install_contract = {
            "scripts/install_familybot.py": "does not include the supported installer",
            "scripts/manage_database.py backup": "does not include the supported backup command",
            "scripts/manage_database.py restore": "does not include the supported restore command",
            "--demo": "does not include the fictional demonstration path",
            "22.22.3": "does not pin the tested Node.js baseline",
            "Python | `3.12`": "does not pin the Python 3.12 baseline",
            "minimal OpenClaw footprint": "does not explain the minimal OpenClaw footprint",
            "scripts/check_setup.py --mode source": "does not include the source readiness check",
            "scripts/check_setup.py --mode runtime": "does not include the runtime readiness check",
            "--profile dashboard": "does not include the dashboard readiness profile",
            "himalaya account configure": "does not include guided mail setup",
            "scripts/deploy_core.sh --reload": "does not include Core deployment",
            "$HOME/.familybot": "does not document the standalone private workspace",
            "--upgrade --writers-stopped": "does not document explicit stopped-writer upgrades",
            "--portal-runtime": "does not retain the selected upgrade runtime",
            "--replace-school-calendar": "does not explain explicit school-date replacement",
            "pre-upgrade": "does not explain whole-upgrade backup and recovery",
        }
        for marker, message in required_install_contract.items():
            if marker not in content:
                errors.append(f"GETTING_STARTED.md {message}")

    for document in markdown_files(root):
        content = document.read_text(encoding="utf-8")
        relative_document = document.relative_to(root)
        if content.count("```") % 2:
            errors.append(f"unbalanced fenced code block: {relative_document}")
        for raw_target in MARKDOWN_LINK.findall(content):
            target = local_link_target(document, raw_target)
            if target is not None and not target.exists():
                errors.append(f"broken local link in {relative_document}: {raw_target}")

    public_templates = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("family.example.json")
        if {".git", ".venv", "node_modules"}.isdisjoint(path.parts)
    )
    if public_templates != ["config/family.example.json"]:
        errors.append(
            "expected exactly one public family template at config/family.example.json; "
            f"found {public_templates}"
        )

    legacy_phrases = {
        "not direct users yet": "vision still says children are not direct users",
        "external smart-home, menu and camera integrations are ideas":
            "getting-started guide has the obsolete Smart Home boundary",
        "python 3.9+": "installation documentation still advertises unsupported Python 3.9",
        "not yet a one-command installer for every historical schedule":
            "installation documentation still describes the incomplete LaunchAgent set",
        "current clean-install limitation":
            "installation documentation still describes empty database creation as unsupported",
        "supported starter or restored database":
            "documentation still requires an owner-provided starter database",
    }
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in markdown_files(root))
    for phrase, message in legacy_phrases.items():
        if phrase in combined:
            errors.append(message)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate_repository(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Documentation validation failed with {len(errors)} error(s).")
        return 1
    count = len(markdown_files(args.root.resolve()))
    print(f"Documentation validation OK: {count} Markdown files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
