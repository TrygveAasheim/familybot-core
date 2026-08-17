#!/usr/bin/env python3
"""Reliability primitives shared by FamilyBot jobs.

This module deliberately has no OpenClaw dependency.  It provides the small,
deterministic pieces that must continue to work when inference or Telegram is
unavailable: safe SQLite connections, atomic state files, and a durable outbox.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional


DEFAULT_WORKSPACE = Path.home() / ".openclaw/workspace"


def workspace_path() -> Path:
    return Path(os.environ.get("FAMILYBOT_WORKSPACE", str(DEFAULT_WORKSPACE)))


def database_path() -> Path:
    return Path(os.environ.get("FAMILYBOT_DB_PATH", str(workspace_path() / "db" / "family.db")))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def connect_db(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open SQLite with the safety settings expected by every job."""
    resolved = Path(path or database_path())
    conn = sqlite3.connect(str(resolved), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def atomic_write_json(path: Path, payload: object) -> None:
    """Replace a JSON state file atomically so readers never see partial data."""
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 text file atomically and flush it to disk first."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class DeliveryResult:
    sent: int
    failed: int
    expired: int

    @property
    def ok(self) -> bool:
        return self.failed == 0


class DeliveryOutbox:
    """SQLite-backed, idempotent Telegram delivery queue."""

    def __init__(self, db_path: Optional[Path] = None, clock: Callable[[], datetime] = utc_now):
        self.db_path = Path(db_path or database_path())
        self.clock = clock
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return connect_db(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    channel TEXT NOT NULL,
                    target TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sending', 'sent', 'expired')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    expires_at TEXT,
                    lease_until TEXT,
                    sent_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_delivery_outbox_due
                ON delivery_outbox(status, next_attempt_at)
                """
            )

    def enqueue(
        self,
        *,
        idempotency_key: str,
        target: str,
        payload: str,
        kind: str,
        channel: str = "telegram",
        expires_at: Optional[datetime] = None,
    ) -> int:
        if not idempotency_key.strip() or not target.strip() or not payload.strip():
            raise ValueError("idempotency_key, target and payload must be non-empty")
        now = iso_utc(self.clock())
        expiry = iso_utc(expires_at) if expires_at else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO delivery_outbox
                    (idempotency_key, channel, target, kind, payload, status,
                     attempts, created_at, updated_at, next_attempt_at, expires_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    payload = CASE
                        WHEN delivery_outbox.status = 'pending' THEN excluded.payload
                        ELSE delivery_outbox.payload
                    END,
                    updated_at = CASE
                        WHEN delivery_outbox.status = 'pending' THEN excluded.updated_at
                        ELSE delivery_outbox.updated_at
                    END
                """,
                (idempotency_key, channel, target, kind, payload, now, now, now, expiry),
            )
            row = conn.execute(
                "SELECT id FROM delivery_outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return int(row["id"])

    def deliver_pending(self, sender: Callable[[str, str], bool], limit: int = 20) -> DeliveryResult:
        """Attempt due messages; keep failures queued with bounded backoff."""
        now_dt = self.clock()
        now = iso_utc(now_dt)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM delivery_outbox
                WHERE (status = 'pending' AND next_attempt_at <= ?)
                   OR (status = 'sending' AND lease_until <= ?)
                ORDER BY created_at, id
                LIMIT ?
                """,
                (now, now, limit),
            ).fetchall()

        sent = failed = expired = 0
        for row in rows:
            if row["expires_at"] and row["expires_at"] <= now:
                with self._connect() as conn:
                    conn.execute(
                        """
                        UPDATE delivery_outbox SET status='expired', updated_at=?, lease_until=NULL
                        WHERE id=? AND status IN ('pending', 'sending')
                        """,
                        (now, row["id"]),
                    )
                expired += 1
                continue

            lease_until = iso_utc(now_dt + timedelta(minutes=2))
            with self._connect() as conn:
                claimed = conn.execute(
                    """
                    UPDATE delivery_outbox
                    SET status='sending', lease_until=?, updated_at=?
                    WHERE id=?
                      AND ((status='pending' AND next_attempt_at <= ?)
                           OR (status='sending' AND lease_until <= ?))
                    """,
                    (lease_until, now, row["id"], now, now),
                )
            if claimed.rowcount != 1:
                continue

            error = None
            try:
                success = bool(sender(row["target"], row["payload"]))
                if not success:
                    error = "sender returned false"
            except Exception as exc:  # delivery failures must not lose queued work
                success = False
                error = f"{type(exc).__name__}: {exc}"

            with self._connect() as conn:
                if success:
                    conn.execute(
                        """
                        UPDATE delivery_outbox
                        SET status='sent', attempts=attempts+1, sent_at=?, updated_at=?,
                            lease_until=NULL, last_error=NULL
                        WHERE id=? AND status='sending'
                        """,
                        (now, now, row["id"]),
                    )
                    sent += 1
                else:
                    attempts = int(row["attempts"]) + 1
                    delay = min(3600, 60 * (2 ** min(attempts - 1, 6)))
                    retry_at = iso_utc(now_dt + timedelta(seconds=delay))
                    conn.execute(
                        """
                        UPDATE delivery_outbox
                        SET status='pending', attempts=?, updated_at=?, next_attempt_at=?,
                            lease_until=NULL, last_error=?
                        WHERE id=? AND status='sending'
                        """,
                        (attempts, now, retry_at, (error or "unknown error")[:500], row["id"]),
                    )
                    failed += 1

        return DeliveryResult(sent=sent, failed=failed, expired=expired)

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM delivery_outbox GROUP BY status"
            ).fetchall()
        result = {"pending": 0, "sending": 0, "sent": 0, "expired": 0}
        result.update({row["status"]: int(row["count"]) for row in rows})
        return result


class EmailProcessingLedger:
    """Durable stage tracking for retryable email ingestion."""

    TERMINAL_STATES = {"processed", "quarantined"}

    def __init__(self, db_path: Optional[Path] = None, clock: Callable[[], datetime] = utc_now):
        self.db_path = Path(db_path or database_path())
        self.clock = clock
        with connect_db(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_processing_state (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )

    def begin(self, message_id: str, subject: str) -> None:
        now = iso_utc(self.clock())
        with connect_db(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO email_processing_state
                    (message_id, subject, status, stage, attempts, first_seen_at, updated_at)
                VALUES (?, ?, 'processing', 'discovered', 1, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    subject=excluded.subject,
                    status='processing',
                    stage='discovered',
                    attempts=email_processing_state.attempts + 1,
                    updated_at=excluded.updated_at,
                    last_error=NULL
                WHERE email_processing_state.status NOT IN ('processed', 'quarantined')
                """,
                (str(message_id), subject, now, now),
            )

    def update(self, message_id: str, stage: str, status: str = "processing", error: Optional[str] = None) -> None:
        now = iso_utc(self.clock())
        with connect_db(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE email_processing_state
                SET stage=?, status=?, updated_at=?, last_error=?
                WHERE message_id=?
                """,
                (stage, status, now, error[:1000] if error else None, str(message_id)),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown email message_id: {message_id}")

    def complete(self, message_id: str, quarantined: bool = False) -> None:
        status = "quarantined" if quarantined else "processed"
        self.update(message_id, stage=status, status=status)

    def fail(self, message_id: str, stage: str, error: str) -> None:
        self.update(message_id, stage=stage, status="failed", error=error)

    def is_terminal(self, message_id: str) -> bool:
        return self.status(message_id) in self.TERMINAL_STATES

    def status(self, message_id: str) -> Optional[str]:
        with connect_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM email_processing_state WHERE message_id=?",
                (str(message_id),),
            ).fetchone()
        return str(row["status"]) if row else None
