#!/usr/bin/env python3
"""
Email routing and guard rail functions for FamilyBot.

All email processing MUST go through resolve_sender() before any data
is written to the database. Never write member_id manually — always
use the resolved value from this module.

Guard rails:
- Content for different configured children is NEVER mixed
- Unknown senders are quarantined, not silently dropped or misrouted
- Every routing decision is logged to routing_audit
- Trinn-based routing (AKS) is explicit and auditable
"""

import sqlite3
import re
import os
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from reliability import connect_db, database_path
from family_config import children, integration, member_names

DB_PATH = str(database_path())

MEMBER_NAMES = member_names()
CHILD_PROFILES = children()
TRINN_TO_MEMBER = {
    str(profile["grade"]): int(profile["member_id"])
    for profile in CHILD_PROFILES if profile.get("grade") is not None
}

# Domains that are trusted school senders even if the name isn't in our rules yet
TRUSTED_SCHOOL_DOMAINS = {
    "info.skoleplattform.no",
}

# Forwarded school mail is unwrapped only for locally configured parent addresses.
PARENT_FORWARD_ADDRESSES = {
    str(address).lower() for address in integration("email").get("forward_addresses", [])
}


@dataclass
class RoutingResult:
    member_id: Optional[int]        # None = whole family / unknown
    member_name: Optional[str]
    category: str                   # 'school' | 'aks' | 'admin' | 'unknown'
    confidence: str                 # 'exact' | 'name' | 'trinn' | 'fallback'
    rule_id: Optional[int]
    notes: str
    quarantine: bool = False        # True = do not auto-process, flag for review


def _get_db():
    return connect_db(DB_PATH)


def extract_forwarded_sender(body: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract original sender name and email from a forwarded message body.
    Handles standard 'From: Name <email>' lines in forwarded blocks.
    Returns (name, email) or (None, None) if not found.
    """
    # Match: From: Display Name <email@domain.com>
    pattern = r'[Ff]rom:\s*([^<\n]+?)\s*<([^>]+)>'
    matches = re.findall(pattern, body)
    for name, email in matches:
        name = name.strip()
        email = email.strip().lower()
        # Skip the forwarding parent's address and use the original sender.
        if email not in PARENT_FORWARD_ADDRESSES:
            return name, email
    return None, None


def resolve_sender(
    message_id: str,
    subject: str,
    raw_sender_email: str,
    raw_sender_name: str,
    body_text: str = "",
) -> RoutingResult:
    """
    Resolve an incoming email to a member and category.
    Logs every decision to routing_audit.
    This is the single entry point — all routing flows through here.
    """
    conn = _get_db()
    c = conn.cursor()

    # Unwrap mail from a configured forwarding parent.
    effective_email = raw_sender_email.lower().strip()
    effective_name = raw_sender_name.strip()
    if effective_email in PARENT_FORWARD_ADDRESSES:
        fwd_name, fwd_email = extract_forwarded_sender(body_text)
        if fwd_email:
            # Classic forwarded message — route on original sender
            effective_email = fwd_email
            effective_name = fwd_name or fwd_email
            result = _do_resolve(c, effective_email, effective_name, body_text)
        else:
            # Direct parent email without a forwarded block: resolve from subject and body.
            resolved = _resolve_member_from_body(body_text + " " + subject)
            result = RoutingResult(
                member_id=resolved,
                member_name=MEMBER_NAMES.get(resolved) if resolved else None,
                category="school",
                confidence="fallback",
                rule_id=None,
                notes=f"Direct parent email. Member resolved from content: {MEMBER_NAMES.get(resolved, 'family')}.",
                quarantine=False,
            )
    else:
        result = _do_resolve(c, effective_email, effective_name, body_text)

    # Write audit log
    c.execute("""
        INSERT INTO routing_audit
            (message_id, subject, raw_sender, matched_rule_id,
             resolved_member_id, resolved_category, confidence, notes)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM routing_audit
            WHERE message_id=?
              AND resolved_member_id IS ?
              AND resolved_category=?
        )
    """, (
        message_id, subject,
        f"{raw_sender_name} <{raw_sender_email}>",
        result.rule_id,
        result.member_id,
        result.category,
        result.confidence,
        result.notes,
        message_id,
        result.member_id,
        result.category,
    ))
    conn.commit()
    conn.close()
    return result


def _do_resolve(c, email: str, name: str, body: str) -> RoutingResult:
    email_lower = email.lower().strip()
    name_lower = name.lower().strip()

    # 1. Exact email + name match
    rows = c.execute("""
        SELECT id, member_id, category, trinn, notes, sender_name
        FROM email_senders
        WHERE lower(email_address) = ?
        ORDER BY sender_name
    """, (email_lower,)).fetchall()

    if rows:
        # Try to match on sender name
        for row in rows:
            rule_id, member_id, category, trinn, notes, rule_name = row
            if rule_name and rule_name.lower() in name_lower:
                # Direct name match
                if member_id:
                    return RoutingResult(
                        member_id=member_id,
                        member_name=MEMBER_NAMES.get(member_id),
                        category=category,
                        confidence="exact",
                        rule_id=rule_id,
                        notes=f"Matched sender rule: {rule_name}",
                    )
                elif trinn:
                    # AKS: resolve via trinn mention in body
                    resolved = _resolve_aks_trinn(body, trinn)
                    return RoutingResult(
                        member_id=resolved,
                        member_name=MEMBER_NAMES.get(resolved) if resolved else None,
                        category=category,
                        confidence="trinn",
                        rule_id=rule_id,
                        notes=f"AKS sender {rule_name}, trinn {trinn} → {MEMBER_NAMES.get(resolved, 'family')}",
                    )
                else:
                    # Admin / whole-school
                    return RoutingResult(
                        member_id=None,
                        member_name=None,
                        category=category,
                        confidence="name",
                        rule_id=rule_id,
                        notes=f"Admin/whole-school sender: {rule_name}",
                    )

        # Email domain matched but no name match — still process, but as family/school
        # Try to detect member from body content before falling back to family-wide
        resolved = _resolve_member_from_body(body)
        return RoutingResult(
            member_id=resolved,
            member_name=MEMBER_NAMES.get(resolved) if resolved else None,
            category="school",
            confidence="fallback",
            rule_id=None,
            notes=f"Known domain skoleplattform.no, unrecognised sender '{name}'. Processed as school/{'family' if not resolved else MEMBER_NAMES.get(resolved)}. Add sender to rules if recurring.",
            quarantine=False,
        )

    # 2. No rule match — check if domain is a trusted school domain
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""
    if domain in TRUSTED_SCHOOL_DOMAINS:
        resolved = _resolve_member_from_body(body)
        return RoutingResult(
            member_id=resolved,
            member_name=MEMBER_NAMES.get(resolved) if resolved else None,
            category="school",
            confidence="fallback",
            rule_id=None,
            notes=f"Trusted school domain, unrecognised sender '{name}'. Processed as school/{MEMBER_NAMES.get(resolved, 'family')}. Add to sender rules if recurring.",
            quarantine=False,
        )

    # 3. Truly unknown — quarantine
    return RoutingResult(
        member_id=None,
        member_name=None,
        category="unknown",
        confidence="fallback",
        rule_id=None,
        notes=f"Unknown sender: {name} <{email}>. Quarantined for review.",
        quarantine=True,
    )


def _grade_patterns() -> dict[int, list[str]]:
    patterns: dict[int, list[str]] = {}
    for profile in CHILD_PROFILES:
        if profile.get("grade") is None:
            continue
        member_id = int(profile["member_id"])
        grade = re.escape(str(profile["grade"]))
        patterns[member_id] = [rf"{grade}\.\s*trinn", rf"\b{grade}[abc]\b"]
    return patterns


def _resolve_member_from_body(body: str) -> Optional[int]:
    """
    Best-effort: scan body for child name or trinn mentions.
    Returns member_id if exactly one child is clearly referenced, else None.
    """
    body_lower = body.lower()
    hits = {}

    for profile in CHILD_PROFILES:
        member_id = int(profile["member_id"])
        name = str(profile.get("name") or "").lower()
        if name and re.search(rf"\b{re.escape(name)}\b", body_lower):
            hits[member_id] = hits.get(member_id, 0) + 2

    trinn_patterns = _grade_patterns()
    for member_id, patterns in trinn_patterns.items():
        for pat in patterns:
            if re.search(pat, body_lower):
                hits[member_id] = hits.get(member_id, 0) + 1

    if len(hits) == 1:
        return list(hits.keys())[0]
    return None  # ambiguous or family-wide


def _resolve_aks_trinn(body: str, default_trinn: str) -> Optional[int]:
    """
    For AKS emails, detect which trinn is mentioned in the body.
    Returns member_id or None (family-wide).
    """
    body_lower = body.lower()

    trinn_patterns = _grade_patterns()

    matches = {}
    for member_id, patterns in trinn_patterns.items():
        for pat in patterns:
            if re.search(pat, body_lower):
                matches[member_id] = matches.get(member_id, 0) + 1

    if len(matches) == 1:
        return list(matches.keys())[0]
    elif len(matches) > 1:
        # Multiple trinn mentioned — family-wide
        return None
    else:
        # Fall back to default trinn from rule
        return TRINN_TO_MEMBER.get(default_trinn)


def assert_no_member_mix(events: list, expected_member_id: int):
    """
    Guard: raise if any event in the list has a different member_id.
    Call this before bulk-inserting calendar events from a single email.
    """
    for event in events:
        mid = event.get("member_id")
        if mid is not None and mid != expected_member_id:
            raise ValueError(
                f"Member mix detected! Expected member {expected_member_id} "
                f"({MEMBER_NAMES.get(expected_member_id)}), "
                f"got {mid} ({MEMBER_NAMES.get(mid)}). "
                f"Event: {event.get('title')}"
            )


def get_routing_audit(limit: int = 20) -> list:
    """Return recent routing decisions for review."""
    conn = _get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT routed_at, raw_sender, resolved_member_id,
               resolved_category, confidence, notes, quarantine
        FROM routing_audit
        ORDER BY routed_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows


def get_quarantined(limit: int = 20) -> list:
    """Return emails that need manual review."""
    conn = _get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT routed_at, message_id, subject, raw_sender, notes
        FROM routing_audit
        WHERE quarantine = 1
        ORDER BY routed_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    print(f"Configured routing for {len(CHILD_PROFILES)} child profile(s).")
