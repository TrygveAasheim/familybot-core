#!/usr/bin/env python3
"""Asynchronously turn layout evidence into validated ukeplan items."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, os.path.dirname(__file__))
from reliability import connect_db, database_path, workspace_path


OPENCLAW = "/opt/homebrew/bin/openclaw"
INTERPRETER_VERSION = "ukeplan-llm-v3-extract-review"
WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag"]
CATEGORIES = {"homework", "bring", "event", "subject", "notice", "general"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS week_plan_interpretations (
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
);
CREATE INDEX IF NOT EXISTS idx_week_plan_interpretations_status
    ON week_plan_interpretations(status, updated_at);
"""


def now_text() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_schema(connection) -> None:
    connection.executescript(SCHEMA)


def source_hash(layout_json: str) -> str:
    return hashlib.sha256(layout_json.encode("utf-8")).hexdigest()


def pdf_page_blocks(pdf_path: str) -> list[dict[str, Any]]:
    """Extract page text only for validating model claims, not for semantics."""
    path = Path(pdf_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"source PDF is unavailable: {path}")
    with pdfplumber.open(path) as pdf:
        return [
            {"id": f"pdf-page-{number}", "page": number, "text": page.extract_text() or ""}
            for number, page in enumerate(pdf.pages, start=1)
        ]


def expected_dates(year: int, week: int) -> list[str]:
    monday = dt.date.fromisocalendar(year, week, 1)
    return [(monday + dt.timedelta(days=offset)).isoformat() for offset in range(5)]


def normalize_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def grounded_references(text: str, references: Any, block_text: dict[str, str]) -> list[str]:
    """Accept light model whitespace/paraphrase variation without accepting invention."""
    if not isinstance(references, list) or not references:
        raise ValueError("each item needs valid source_blocks")
    requested = [str(ref) for ref in references if str(ref) in block_text]
    if not requested:
        raise ValueError("each item needs valid source_blocks")
    normalized = normalize_text(text)
    exact = [ref for ref in requested if normalized and normalized in normalize_text(block_text[ref])]
    if exact:
        return exact

    text_tokens = set(normalized.split())
    if len(text_tokens) < 3:
        raise ValueError("item text was not found in its source evidence")
    candidates = []
    for ref, evidence in block_text.items():
        evidence_tokens = set(normalize_text(evidence).split())
        overlap = len(text_tokens & evidence_tokens) / len(text_tokens)
        candidates.append((overlap, ref))
    best_overlap, best_ref = max(candidates, default=(0, ""))
    if best_overlap < 0.8:
        raise ValueError("item text was not found in its source evidence")
    return [best_ref]


def normalize_notes(notes: Any, label: str, block_text: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(notes, list):
        raise ValueError(f"{label} must be a list")
    normalized = []
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError(f"each {label} entry must be an object")
        text = str(note.get("text") or "").strip()
        if not text or len(text) > 600:
            raise ValueError(f"{label} entries need text and source_blocks")
        normalized.append({
            "text": text,
            "source_blocks": grounded_references(text, note.get("source_blocks"), block_text),
        })
    return normalized


def parse_model_json(value: str) -> dict[str, Any]:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM response root must be an object")
    return parsed


def validate_interpretation(payload: dict[str, Any], *, year: int, week: int, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    allowed_dates = expected_dates(year, week)
    block_text = {str(item.get("id")): str(item.get("text") or "") for item in blocks}
    days = payload.get("days")
    if not isinstance(days, list):
        raise ValueError("days must be a list")

    normalized_days = []
    seen_dates = set()
    for day in days:
        if not isinstance(day, dict):
            raise ValueError("each day must be an object")
        date_value = str(day.get("date") or "")
        if date_value not in allowed_dates or date_value in seen_dates:
            raise ValueError(f"invalid or duplicate day date: {date_value}")
        seen_dates.add(date_value)
        items = day.get("items", [])
        if not isinstance(items, list):
            raise ValueError("day items must be a list")
        normalized_items = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each day item must be an object")
            category = str(item.get("category") or "")
            text = str(item.get("text") or "").strip()
            references = item.get("source_blocks")
            confidence = item.get("confidence")
            if category not in CATEGORIES or not text or len(text) > 600:
                raise ValueError("invalid day item category or text")
            normalized_references = grounded_references(text, references, block_text)
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError) as exc:
                raise ValueError("item confidence must be numeric") from exc
            if not 0 <= confidence_value <= 1:
                raise ValueError("item confidence must be between 0 and 1")
            normalized_items.append({
                "category": category,
                "text": text,
                "source_blocks": normalized_references,
                "confidence": round(confidence_value, 3),
            })
        weekday = WEEKDAYS[dt.date.fromisoformat(date_value).weekday()]
        normalized_days.append({"date": date_value, "weekday": weekday, "items": normalized_items})

    weekly_tasks = payload.get("weekly_tasks", payload.get("general_notes", []))
    general_info = payload.get("general_info", [])
    normalized_tasks = normalize_notes(weekly_tasks, "weekly_tasks", block_text)
    normalized_info = normalize_notes(general_info, "general_info", block_text)

    return {
        "version": 2,
        "week": week,
        "year": year,
        "days": sorted(normalized_days, key=lambda item: item["date"]),
        "weekly_tasks": normalized_tasks,
        "general_info": normalized_info,
    }


def prompt_for_plan(year: int, week: int, layout: dict[str, Any], pdf_path: str | None = None) -> str:
    if pdf_path:
        dates = expected_dates(year, week)
        return f"""You are extracting a Norwegian school ukeplan from the original PDF.

Read every page of this local PDF with the PDF-reading capability:
{pdf_path}

The PDF is the only source of truth. Read every page before answering. Do not
use email text, filenames, memory, or a previous parser result. This is ISO
week {week}/{year}; valid weekday dates are {', '.join(dates)}.

Put information tied to a specific weekday under that day's items. Put actions
that apply to the whole week or have no single day (reading, homework,
equipment, routines) in weekly_tasks. Put notices, themes, school-hour
reminders and other information that is not an action in general_info. Do not
put the same point in more than one bucket. Preserve the original Norwegian
wording. Do not invent, summarize, or omit meaningful plan content.

Return JSON only, exactly in this shape (days is an array, never an object):
{{
  "days": [{{"date": "YYYY-MM-DD", "items": [{{
    "category": "homework|bring|event|subject|notice|general",
    "text": "verbatim text from the PDF",
    "source_blocks": ["pdf-page-2"],
    "confidence": 0.0
  }}]}}],
  "weekly_tasks": [{{"text": "verbatim text from the PDF", "source_blocks": ["pdf-page-1"]}}],
  "general_info": [{{"text": "verbatim text from the PDF", "source_blocks": ["pdf-page-1"]}}]
}}

Use source_blocks to name the PDF page(s) supporting each item. Include every
meaningful homework, bring-item, event and notice once, grouped under the day
where the PDF places it. Return an empty list only when the PDF truly has no
content for that section. The days value must be an array, never an object.
"""
    blocks = layout.get("source_blocks") or []
    evidence = "\n".join(
        f"{item.get('id')}: page={item.get('page')} weekday={item.get('weekday', 'general')} text={item.get('text', '')}"
        for item in blocks
    )
    dates = expected_dates(year, week)
    return f"""You classify a Norwegian school ukeplan. Return JSON only.

The plan is ISO week {week}/{year}. Valid weekday dates are: {', '.join(dates)}.
Use only the supplied evidence. Do not invent, summarize or merge away source
details. Each output text must be copied verbatim from one or more source
blocks, apart from harmless whitespace normalization.

Return exactly this shape:
{{
  "days": [{{"date": "YYYY-MM-DD", "items": [{{"category": "homework|bring|event|subject|notice|general", "text": "verbatim text", "source_blocks": ["page2-block3"], "confidence": 0.0}}]}}],
  "weekly_tasks": [{{"text": "verbatim text", "source_blocks": ["page1-block4"]}}],
  "general_info": [{{"text": "verbatim text", "source_blocks": ["page1-block5"]}}]
}}

Include a day only when there is evidence for it. Keep every source item
assigned at most once.

EVIDENCE:
{evidence}
"""


def review_prompt(year: int, week: int, pdf_path: str, extraction: dict[str, Any]) -> str:
    dates = expected_dates(year, week)
    extraction_json = json.dumps(extraction, ensure_ascii=False, indent=2)
    return f"""You are the completeness reviewer for a Norwegian school ukeplan.

Reread every page of the original PDF with the PDF-reading capability:
{pdf_path}

Audit the proposed extraction below against the entire PDF. Recover any
meaningful missed point, remove anything not supported by the PDF, and move
misclassified points into the correct bucket. Information tied to a weekday
belongs in that day's items. Whole-week actions belong in weekly_tasks.
Non-action notices and practical information belong in general_info. Do not
duplicate a point. Preserve Norwegian wording and cite the supporting page as
source_blocks using pdf-page-N. Do not use filenames, email text, memory, or
anything outside the PDF. Valid dates are {', '.join(dates)}.

PROPOSED EXTRACTION:
{extraction_json}

Return JSON only, exactly the same shape:
{{
  "days": [{{"date": "YYYY-MM-DD", "items": [{{"category": "homework|bring|event|subject|notice|general", "text": "verbatim text", "source_blocks": ["pdf-page-2"], "confidence": 0.0}}]}}],
  "weekly_tasks": [{{"text": "verbatim text", "source_blocks": ["pdf-page-1"]}}],
  "general_info": [{{"text": "verbatim text", "source_blocks": ["pdf-page-1"]}}]
}}
"""


def invoke_model(prompt: str) -> str:
    result = subprocess.run(
        [OPENCLAW, "agent", "--agent", "main", "--thinking", "low", "--message", prompt, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(f"OpenClaw failed: {(result.stderr or result.stdout)[:240]}")
    response = json.loads(result.stdout)
    payloads = response.get("result", {}).get("payloads", [])
    if not payloads or not payloads[0].get("text"):
        raise RuntimeError("OpenClaw returned no interpretation")
    return str(payloads[0]["text"])


def mark_failed(db_path: Path, interpretation_id: int, error: str) -> None:
    with connect_db(db_path) as connection:
        connection.execute(
            """UPDATE week_plan_interpretations
               SET status='failed', last_error=?, updated_at=? WHERE id=?""",
            (error[:500], now_text(), interpretation_id),
        )


def interpret_one(db_path: Path, row: Any) -> bool:
    plan_id, week, year, layout_json, interpretation_id = row
    try:
        layout = json.loads(layout_json)
        pdf_path = str(layout.get("source_pdf") or "").strip() or None
        blocks = pdf_page_blocks(pdf_path) if pdf_path else (layout.get("source_blocks") or [])
        if not blocks:
            raise ValueError("plan has no layout evidence")
        model_text = invoke_model(prompt_for_plan(int(year), int(week), layout, pdf_path))
        normalized = validate_interpretation(
            parse_model_json(model_text), year=int(year), week=int(week), blocks=blocks
        )
        if pdf_path:
            try:
                reviewed_text = invoke_model(review_prompt(int(year), int(week), pdf_path, normalized))
                normalized = validate_interpretation(
                    parse_model_json(reviewed_text), year=int(year), week=int(week), blocks=blocks
                )
            except Exception as exc:
                print(f"[UKEPLAN] Review fallback for plan {plan_id}: {type(exc).__name__}")
        with connect_db(db_path) as connection:
            connection.execute(
                """UPDATE week_plan_interpretations
                   SET status='accepted', model='openclaw', structured_json=?, last_error=NULL,
                       updated_at=? WHERE id=?""",
                (json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), now_text(), interpretation_id),
            )
        print(f"[UKEPLAN] Accepted interpretation for plan {plan_id}")
        return True
    except Exception as exc:
        mark_failed(db_path, interpretation_id, f"{type(exc).__name__}: {exc}")
        print(f"[UKEPLAN] Interpretation failed for plan {plan_id}: {type(exc).__name__}")
        return False


def run(limit: int = 1, plan_id: int | None = None) -> int:
    db_path = database_path()
    with connect_db(db_path) as connection:
        ensure_schema(connection)
        stale_before = dt.datetime.now().astimezone() - dt.timedelta(minutes=30)
        for stale in connection.execute(
            "SELECT id,updated_at FROM week_plan_interpretations WHERE status='processing'"
        ).fetchall():
            try:
                is_stale = dt.datetime.fromisoformat(str(stale[1])) < stale_before
            except (TypeError, ValueError):
                is_stale = True
            if is_stale:
                connection.execute(
                    "UPDATE week_plan_interpretations SET status='pending',last_error=?,updated_at=? WHERE id=?",
                    ("Recovered stale interpretation lease", now_text(), stale[0]),
                )
        plans = connection.execute(
            """SELECT w.id,w.week_number,w.year,w.layout_json,
                      i.id AS interpretation_id,i.source_hash,i.status
               FROM week_plans w
               LEFT JOIN week_plan_interpretations i ON i.week_plan_id=w.id
               WHERE COALESCE(w.layout_json,'') <> ''
                 AND (? IS NULL OR w.id=?)
               ORDER BY w.created_at DESC,w.id DESC""",
            (plan_id, plan_id),
        ).fetchall()
        work = []
        for item in plans:
            current_hash = source_hash(item[3])
            if item[4] is None:
                cursor = connection.execute(
                    """INSERT INTO week_plan_interpretations
                       (week_plan_id,status,source_hash,parser_version,structured_json,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (item[0], "pending", current_hash, INTERPRETER_VERSION, "{}", now_text()),
                )
                interpretation_id = cursor.lastrowid
                status = "pending"
            elif item[5] != current_hash or item[6] == "failed":
                connection.execute(
                    """UPDATE week_plan_interpretations
                       SET status='pending',source_hash=?,parser_version=?,structured_json='{}',last_error=NULL,updated_at=?
                       WHERE id=?""",
                    (current_hash, INTERPRETER_VERSION, now_text(), item[4]),
                )
                interpretation_id = item[4]
                status = "pending"
            else:
                interpretation_id = item[4]
                status = item[6]
            if status in {"pending", "failed"} and len(work) < limit:
                connection.execute(
                    "UPDATE week_plan_interpretations SET status='processing',attempts=attempts+1,updated_at=? WHERE id=?",
                    (now_text(), interpretation_id),
                )
                work.append((item[0], item[1], item[2], item[3], interpretation_id))

    for row in work:
        interpret_one(db_path, row)
    print(f"[UKEPLAN] Interpretation candidates processed: {len(work)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--plan-id", type=int)
    args = parser.parse_args()
    raise SystemExit(run(max(1, min(args.limit, 10)), args.plan_id))
