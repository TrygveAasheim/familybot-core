#!/usr/bin/env python3
"""Rebuild stored ukeplan text from the original PDF attachments.

This is a one-time privacy repair for rows written by older ingestion code.
It deliberately refuses to use email bodies or email-log summaries as plan
content. Missing attachments are reported and left untouched for safe retry.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))

import process_emails


def main() -> int:
    connection = process_emails.get_db()
    rows = connection.execute(
        """SELECT w.id,w.member_id,w.source_email_id,e.subject,e.summary
           FROM week_plans w
           JOIN email_log e ON e.message_id=CAST(w.source_email_id AS TEXT)
           WHERE e.has_pdf=1
           ORDER BY w.id"""
    ).fetchall()

    repaired = 0
    skipped = 0
    for plan_id, member_id, email_id, subject, email_summary in rows:
        paths = []
        for name in process_emails.declared_attachment_names(email_summary or ""):
            path = os.path.join(process_emails.ATTACHMENT_DIR, os.path.basename(name))
            if path.lower().endswith(".pdf") and os.path.isfile(path):
                paths.append(path)
        if not paths:
            skipped += 1
            redact_plan_without_pdf(connection, plan_id)
            print(f"[SKIP] plan {plan_id}: PDF attachment unavailable")
            continue
        try:
            process_emails.save_ukeplan_attachments(
                paths, member_id, email_id, subject=subject
            )
            repaired += 1
            print(f"[OK] plan {plan_id}: rebuilt from PDF")
        except RuntimeError:
            skipped += 1
            redact_plan_without_pdf(connection, plan_id)
            print(f"[SKIP] plan {plan_id}: PDF could not be parsed")

    legacy_rows = connection.execute(
        """SELECT w.id,w.raw_text,w.summary,COALESCE(e.has_pdf,0)
           FROM week_plans w LEFT JOIN email_log e
             ON e.message_id=CAST(w.source_email_id AS TEXT)
           WHERE COALESCE(e.has_pdf,0)=0"""
    ).fetchall()
    scrubbed = 0
    for plan_id, raw_text, summary, _has_pdf in legacy_rows:
        clean_raw = process_emails.strip_email_metadata(raw_text or "")
        clean_summary = process_emails.strip_email_metadata(summary or "")
        if clean_raw != (raw_text or "") or clean_summary != (summary or ""):
            connection.execute(
                "UPDATE week_plans SET raw_text=?, summary=? WHERE id=?",
                (clean_raw, clean_summary, plan_id),
            )
            scrubbed += 1
    connection.commit()
    connection.close()
    print(f"Rebuilt {repaired} ukeplan row(s); skipped {skipped}; scrubbed {scrubbed} legacy row(s).")
    return 0


def redact_plan_without_pdf(connection: sqlite3.Connection, plan_id: int) -> None:
    """Remove unverifiable legacy text rather than retain mail content."""
    connection.execute(
        "UPDATE week_plans SET raw_text='', summary=? WHERE id=?",
        (f"Ukeplan (PDF-innhold kunne ikke leses for denne planen.)", plan_id),
    )
    connection.commit()


if __name__ == "__main__":
    raise SystemExit(main())
