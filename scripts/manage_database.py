#!/usr/bin/env python3
"""Initialize, migrate, inspect and back up the FamilyBot database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from database_migrations import (
    MigrationError,
    apply_migrations,
    backup_database,
    initialize_database,
    migration_status,
    restore_database,
)
from family_config import workspace_path


def parser() -> argparse.ArgumentParser:
    workspace = workspace_path()
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=("init", "migrate", "status", "backup", "restore"))
    value.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("FAMILYBOT_DB_PATH", workspace / "db/family.db")),
    )
    value.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("FAMILYBOT_FAMILY_CONFIG", workspace / "config/family.local.json")),
    )
    value.add_argument("--backup-root", type=Path, default=workspace / "backups")
    value.add_argument("--from-backup", type=Path)
    value.add_argument("--writers-stopped", action="store_true",
                       help="confirm all database users are stopped before restore; this does not stop them")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "init":
            result = initialize_database(args.db, args.config, args.backup_root)
        elif args.command == "migrate":
            result = apply_migrations(args.db, backup_root=args.backup_root)
        elif args.command == "backup":
            result = {"backup": str(backup_database(args.db, args.backup_root, label="manual"))}
        elif args.command == "restore":
            if not args.writers_stopped:
                raise MigrationError("restore requires --writers-stopped after stopping all database users")
            if args.from_backup is None:
                raise MigrationError("restore requires --from-backup")
            result = restore_database(args.db, args.from_backup, args.backup_root)
        else:
            result = migration_status(args.db)
    except MigrationError as exc:
        print(f"Database operation failed safely: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
