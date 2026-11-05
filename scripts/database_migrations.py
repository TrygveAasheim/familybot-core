#!/usr/bin/env python3
"""Versioned, transactional ownership of the FamilyBot Core SQLite schema.

This module is intentionally stdlib-only so a new household can initialize its
database before any optional integration or model runtime exists.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

CORE_COMPONENT = "core"
CORE_SCHEMA_VERSION = 1

MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS familybot_schema_migrations (
    component TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY(component, version)
)
"""


CORE_BASELINE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS family_members (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('parent','child')),
        grade TEXT,
        school TEXT,
        teacher TEXT,
        telegram_id TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS email_senders (
        id INTEGER PRIMARY KEY,
        email_address TEXT NOT NULL,
        sender_name TEXT,
        member_id INTEGER REFERENCES family_members(id),
        category TEXT NOT NULL DEFAULT 'school',
        trinn TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_email_senders_address
        ON email_senders(email_address)""",
    """CREATE TABLE IF NOT EXISTS routing_audit (
        id INTEGER PRIMARY KEY,
        message_id TEXT NOT NULL,
        subject TEXT,
        raw_sender TEXT,
        matched_rule_id INTEGER REFERENCES email_senders(id),
        resolved_member_id INTEGER REFERENCES family_members(id),
        resolved_category TEXT NOT NULL,
        confidence TEXT NOT NULL,
        notes TEXT,
        quarantine INTEGER NOT NULL DEFAULT 0 CHECK(quarantine IN (0,1)),
        routed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_routing_audit_message
        ON routing_audit(message_id)""",
    """CREATE TABLE IF NOT EXISTS calendar_events (
        id INTEGER PRIMARY KEY,
        member_id INTEGER REFERENCES family_members(id),
        title TEXT NOT NULL,
        event_date TEXT NOT NULL,
        event_time TEXT,
        end_date TEXT,
        location TEXT,
        description TEXT,
        bring TEXT,
        requires_response INTEGER NOT NULL DEFAULT 0 CHECK(requires_response IN (0,1)),
        response_deadline TEXT,
        source TEXT NOT NULL DEFAULT 'manual',
        source_ref TEXT,
        week_number INTEGER,
        year INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(member_id, title, event_date, source, source_ref)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_calendar_events_date
        ON calendar_events(event_date, member_id)""",
    """CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY,
        member_id INTEGER REFERENCES family_members(id),
        name TEXT NOT NULL,
        description TEXT,
        location TEXT,
        schedule TEXT,
        spond_group_id TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        paused_until TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS kanban_cards (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        assigned_to TEXT,
        lane TEXT NOT NULL DEFAULT 'todo',
        priority TEXT NOT NULL DEFAULT 'nice-to',
        due_date TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        archived_at TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_kanban_cards_active
        ON kanban_cards(archived_at, lane, assigned_to)""",
    """CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY,
        message_id TEXT NOT NULL UNIQUE,
        subject TEXT,
        sender TEXT,
        received_at TEXT,
        processed_at TEXT,
        member_id INTEGER REFERENCES family_members(id),
        category TEXT,
        has_pdf INTEGER NOT NULL DEFAULT 0 CHECK(has_pdf IN (0,1)),
        summary TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_email_log_received
        ON email_log(received_at DESC)""",
    """CREATE TABLE IF NOT EXISTS week_plans (
        id INTEGER PRIMARY KEY,
        member_id INTEGER NOT NULL REFERENCES family_members(id),
        week_number INTEGER NOT NULL CHECK(week_number BETWEEN 1 AND 53),
        year INTEGER NOT NULL CHECK(year BETWEEN 2000 AND 2200),
        raw_text TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        source_email_id TEXT,
        teacher TEXT,
        layout_json TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_week_plans_member_period
        ON week_plans(member_id, year, week_number, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS week_plan_days (
        id INTEGER PRIMARY KEY,
        week_plan_id INTEGER NOT NULL REFERENCES week_plans(id) ON DELETE CASCADE,
        day TEXT NOT NULL,
        date TEXT,
        subject TEXT,
        note TEXT,
        homework TEXT,
        bring TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_week_plan_days_plan
        ON week_plan_days(week_plan_id, date, id)""",
    """CREATE TABLE IF NOT EXISTS norwegian_holidays (
        date TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS school_calendar (
        id INTEGER PRIMARY KEY,
        year_label TEXT NOT NULL,
        event_type TEXT NOT NULL,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        applies_to TEXT NOT NULL DEFAULT 'all',
        notes TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_school_calendar_dates
        ON school_calendar(start_date, end_date)""",
    """CREATE TABLE IF NOT EXISTS school_years (
        year_label TEXT PRIMARY KEY,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        notes TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS spond_events (
        id TEXT PRIMARY KEY,
        group_id TEXT,
        group_name TEXT,
        member_id INTEGER REFERENCES family_members(id),
        title TEXT,
        event_date TEXT,
        event_end TEXT,
        location TEXT,
        description TEXT,
        rsvp_accepted INTEGER NOT NULL DEFAULT 0,
        rsvp_declined INTEGER NOT NULL DEFAULT 0,
        rsvp_unanswered INTEGER NOT NULL DEFAULT 0,
        my_rsvp TEXT,
        rsvp_deadline TEXT,
        requires_response INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT,
        first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notified INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE INDEX IF NOT EXISTS idx_spond_events_date
        ON spond_events(event_date, member_id)""",
    """CREATE TABLE IF NOT EXISTS spond_messages (
        id TEXT PRIMARY KEY,
        group_id TEXT,
        group_name TEXT,
        member_id INTEGER REFERENCES family_members(id),
        sender_name TEXT,
        text TEXT,
        sent_at TEXT,
        first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notified INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS delivery_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idempotency_key TEXT NOT NULL UNIQUE,
        channel TEXT NOT NULL,
        target TEXT NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','sending','sent','expired')),
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        next_attempt_at TEXT NOT NULL,
        expires_at TEXT,
        lease_until TEXT,
        sent_at TEXT,
        last_error TEXT
    )""",
    """CREATE INDEX IF NOT EXISTS idx_delivery_outbox_due
        ON delivery_outbox(status, next_attempt_at)""",
    """CREATE TABLE IF NOT EXISTS email_processing_state (
        message_id TEXT PRIMARY KEY,
        subject TEXT,
        status TEXT NOT NULL,
        stage TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS week_plan_interpretations (
        id INTEGER PRIMARY KEY,
        week_plan_id INTEGER NOT NULL UNIQUE REFERENCES week_plans(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('pending','processing','accepted','failed')),
        source_hash TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        model TEXT,
        structured_json TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE INDEX IF NOT EXISTS idx_week_plan_interpretations_status
        ON week_plan_interpretations(status, updated_at)""",
)


REQUIRED_CORE_COLUMNS = {
    "family_members": {"id", "name", "role", "grade", "school", "teacher"},
    "calendar_events": {"id", "member_id", "title", "event_date", "source", "source_ref"},
    "activities": {"id", "member_id", "name", "active", "paused_until"},
    "kanban_cards": {"id", "title", "assigned_to", "lane", "priority", "archived_at"},
    "email_log": {"id", "message_id", "member_id", "processed_at", "summary"},
    "email_senders": {"id", "email_address", "member_id", "category", "trinn"},
    "routing_audit": {"id", "message_id", "resolved_member_id", "quarantine"},
    "week_plans": {"id", "member_id", "week_number", "year", "raw_text", "layout_json"},
    "week_plan_days": {"id", "week_plan_id", "day", "date", "subject", "homework", "bring"},
    "norwegian_holidays": {"date", "name", "kind"},
    "school_calendar": {"id", "year_label", "event_type", "start_date", "end_date"},
    "school_years": {"year_label", "start_date", "end_date"},
}


class MigrationError(RuntimeError):
    """Raised when schema state cannot be safely migrated or verified."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    fingerprint: str

    @property
    def checksum(self) -> str:
        material = f"{CORE_COMPONENT}:{self.version}:{self.name}:{self.fingerprint}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _apply_core_baseline(connection: sqlite3.Connection) -> None:
    for statement in CORE_BASELINE_STATEMENTS:
        connection.execute(statement)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(week_plans)")}
    if columns and "layout_json" not in columns:
        connection.execute("ALTER TABLE week_plans ADD COLUMN layout_json TEXT NOT NULL DEFAULT ''")


CORE_MIGRATIONS = (
    Migration(
        version=1,
        name="core-baseline",
        apply=_apply_core_baseline,
        fingerprint="\n".join(CORE_BASELINE_STATEMENTS),
    ),
)


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def backup_database(database: Path, backup_root: Path, *, label: str = "core-migration") -> Path:
    if not database.is_file():
        raise MigrationError(f"Cannot back up missing database: {database}")
    private_directory(backup_root)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target_dir = backup_root / f"{label}-{stamp}"
    target_dir.mkdir(mode=0o700)
    target = target_dir / "family.db"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".family-", suffix=".db", dir=target_dir)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with connect(database) as source, connect(temporary) as destination:
            source.backup(destination)
        temporary.chmod(0o600)
        verify_database(temporary, require_schema=False)
        os.replace(temporary, target)
        target.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def restore_database(database: Path, source: Path, backup_root: Path) -> dict[str, str | None]:
    database = Path(database).expanduser()
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise MigrationError(f"Restore source is not a file: {source}")
    if database.exists() and source == database.resolve():
        raise MigrationError("Restore source and target must be different files")
    try:
        verify_database(source)
    except (MigrationError, sqlite3.Error) as exc:
        raise MigrationError("Restore source failed database verification") from exc
    recovery = (
        backup_database(database, backup_root, label="pre-restore")
        if database.is_file()
        else None
    )
    private_directory(database.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".family-restore-", suffix=".db", dir=database.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with connect(source) as source_connection, connect(temporary) as destination:
            source_connection.backup(destination)
        temporary.chmod(0o600)
        verify_database(temporary)
        os.replace(temporary, database)
        database.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "restored_from": str(source),
        "recovery_backup": str(recovery) if recovery else None,
    }


def _existing_migrations(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='familybot_schema_migrations'"
    ).fetchone()
    if not exists:
        return {}
    rows = connection.execute(
        """SELECT version,name,checksum,applied_at
           FROM familybot_schema_migrations WHERE component=? ORDER BY version""",
        (CORE_COMPONENT,),
    ).fetchall()
    return {int(row["version"]): row for row in rows}


def _validate_migration_history(existing: dict[int, sqlite3.Row]) -> None:
    known = {migration.version: migration for migration in CORE_MIGRATIONS}
    unknown = sorted(set(existing) - set(known))
    if unknown:
        raise MigrationError(f"Database has unsupported future Core migration(s): {unknown}")
    for version, row in existing.items():
        migration = known[version]
        if row["name"] != migration.name or row["checksum"] != migration.checksum:
            raise MigrationError(f"Core migration {version} does not match reviewed source")


def schema_version(connection: sqlite3.Connection, component: str = CORE_COMPONENT) -> int:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='familybot_schema_migrations'"
    ).fetchone()
    if not table:
        return 0
    row = connection.execute(
        "SELECT MAX(version) FROM familybot_schema_migrations WHERE component=?", (component,)
    ).fetchone()
    return int(row[0] or 0)


def validate_core_schema(connection: sqlite3.Connection) -> None:
    for table, expected in REQUIRED_CORE_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        missing = sorted(expected - columns)
        if missing:
            raise MigrationError(f"Core table {table} is missing column(s): {', '.join(missing)}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise MigrationError("Core schema has foreign-key violations")


def apply_migrations(
    database: Path,
    *,
    backup_root: Path | None = None,
    migrations: Iterable[Migration] = CORE_MIGRATIONS,
) -> dict[str, Any]:
    database = Path(database).expanduser()
    existed = database.exists() and database.stat().st_size > 0
    private_directory(database.parent)
    backup = None
    migrations = tuple(migrations)
    with connect(database) as connection:
        existing = _existing_migrations(connection)
        _validate_migration_history(existing)
        pending = [migration for migration in migrations if migration.version not in existing]
    if existed and pending:
        if backup_root is None:
            raise MigrationError("Existing databases require a backup directory before migration")
        backup = backup_database(database, backup_root)
    applied: list[int] = []
    try:
        with connect(database) as connection:
            existing = _existing_migrations(connection)
            _validate_migration_history(existing)
            for migration in migrations:
                if migration.version in existing:
                    continue
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(MIGRATION_TABLE)
                    migration.apply(connection)
                    validate_core_schema(connection)
                    connection.execute(
                        """INSERT INTO familybot_schema_migrations
                           (component,version,name,checksum,applied_at) VALUES(?,?,?,?,?)""",
                        (
                            CORE_COMPONENT,
                            migration.version,
                            migration.name,
                            migration.checksum,
                            dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                        ),
                    )
                    connection.commit()
                    applied.append(migration.version)
                except BaseException:
                    connection.rollback()
                    raise
            validate_core_schema(connection)
    except BaseException as exc:
        if not existed:
            database.unlink(missing_ok=True)
        raise MigrationError(f"Core migration failed; existing data was not committed: {type(exc).__name__}") from exc
    database.chmod(0o600)
    verify_database(database)
    return {
        "component": CORE_COMPONENT,
        "version": CORE_SCHEMA_VERSION,
        "applied": applied,
        "backup": str(backup) if backup else None,
    }


def seed_members(connection: sqlite3.Connection, config: dict[str, Any]) -> dict[str, int]:
    raw_members = config.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise MigrationError("Configuration must contain at least one member")
    inserted = 0
    updated = 0
    connection.execute("BEGIN IMMEDIATE")
    try:
        for raw in raw_members:
            if not isinstance(raw, dict):
                raise MigrationError("Every configured member must be an object")
            member_id = int(raw["member_id"])
            name = str(raw["name"]).strip()
            role = str(raw["role"])
            if member_id <= 0 or not name or role not in {"parent", "child"}:
                raise MigrationError("Configured member has invalid identity fields")
            existing = connection.execute(
                "SELECT name,role,grade,school,teacher FROM family_members WHERE id=?",
                (member_id,),
            ).fetchone()
            if existing:
                if existing["role"] != role:
                    raise MigrationError(
                        f"Configured member_id {member_id} changes role and conflicts with existing household data"
                    )
                profile = (raw.get("grade"), raw.get("school"), raw.get("teacher"))
                previous = (existing["grade"], existing["school"], existing["teacher"])
                if existing["name"] != name:
                    for card in connection.execute(
                        "SELECT id,assigned_to FROM kanban_cards WHERE assigned_to IS NOT NULL"
                    ).fetchall():
                        if str(card["assigned_to"]).casefold() == str(existing["name"]).casefold():
                            connection.execute(
                                "UPDATE kanban_cards SET assigned_to=? WHERE id=?",
                                (name.lower(), card["id"]),
                            )
                if existing["name"] != name or previous != profile:
                    connection.execute(
                        """UPDATE family_members
                           SET name=?,grade=?,school=?,teacher=? WHERE id=?""",
                        (name, *profile, member_id),
                    )
                    updated += 1
                continue
            connection.execute(
                """INSERT INTO family_members(id,name,role,grade,school,teacher,notes)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    member_id,
                    name,
                    role,
                    raw.get("grade"),
                    raw.get("school"),
                    raw.get("teacher"),
                    None,
                ),
            )
            inserted += 1
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"members_created": inserted, "members_updated": updated}


def member_sync_required(connection: sqlite3.Connection, config: dict[str, Any]) -> bool:
    raw_members = config.get("members")
    if not isinstance(raw_members, list):
        return True
    for raw in raw_members:
        if not isinstance(raw, dict):
            return True
        try:
            member_id = int(raw["member_id"])
            expected = (
                str(raw["name"]).strip(),
                str(raw["role"]),
                raw.get("grade"),
                raw.get("school"),
                raw.get("teacher"),
            )
        except (KeyError, TypeError, ValueError):
            return True
        existing = connection.execute(
            "SELECT name,role,grade,school,teacher FROM family_members WHERE id=?",
            (member_id,),
        ).fetchone()
        if existing is None or tuple(existing) != expected:
            return True
    return False


def initialize_database(
    database: Path,
    config_path: Path,
    backup_root: Path,
) -> dict[str, Any]:
    existed = Path(database).is_file() and Path(database).stat().st_size > 0
    config_path = Path(config_path).expanduser()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MigrationError(f"Cannot read validated family configuration: {config_path}") from exc
    result = apply_migrations(database, backup_root=backup_root)
    with connect(database) as connection:
        sync_required = member_sync_required(connection, config)
    if existed and sync_required and not result.get("backup"):
        result["backup"] = str(
            backup_database(database, backup_root, label="core-profile")
        )
    with connect(database) as connection:
        result.update(seed_members(connection, config))
        validate_core_schema(connection)
    verify_database(database)
    return result


def verify_database(database: Path, *, require_schema: bool = True) -> None:
    with connect(database) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise MigrationError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise MigrationError("SQLite foreign-key check failed")
        if require_schema:
            validate_core_schema(connection)
            if schema_version(connection) != CORE_SCHEMA_VERSION:
                raise MigrationError("Core schema version is not current")


def migration_status(database: Path) -> dict[str, Any]:
    database = Path(database).expanduser()
    if not database.is_file():
        return {"exists": False, "component": CORE_COMPONENT, "version": 0, "current": False}
    with connect(database) as connection:
        version = schema_version(connection)
        integrity = connection.execute("PRAGMA quick_check").fetchone()
    return {
        "exists": True,
        "component": CORE_COMPONENT,
        "version": version,
        "current": version == CORE_SCHEMA_VERSION and bool(integrity and integrity[0] == "ok"),
    }
