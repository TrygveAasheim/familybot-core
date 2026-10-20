#!/usr/bin/env python3
"""
FamilyBot briefing generator — LLM-powered.

Collects structured data from briefing_data.py, passes it to the LLM
for natural text generation, then sends to the configured parents on Telegram.

Usage:
  python3 briefing.py daily     — weekday morning briefing
  python3 briefing.py weekly    — Sunday weekly overview
  python3 briefing.py preview   — print both to stdout without sending
"""

import sys
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from typing import Optional
import zoneinfo

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")

sys.path.insert(0, os.path.dirname(__file__))
from briefing_data import collect_daily, collect_weekly
from family_config import children, parents, family_prompt_context, integration, telegram_recipients
from reliability import DeliveryOutbox, database_path, workspace_path
from outcome_health import record_briefing

RECIPIENTS = telegram_recipients()
FAMILY_CONTEXT = family_prompt_context()
TRANSPORT_CONTEXT = str(integration("transport").get("route_description") or "konfigurert strekning")
CABIN_CONTEXT = str(integration("weather").get("cabin_label") or "sekundær lokasjon")
CHILD_NAMES = {str(profile.get("slug") or f"child_{index + 1}"): str(profile["name"])
               for index, profile in enumerate(children())}
PARENT_NAMES = {str(profile.get("slug") or f"parent_{index + 1}"): str(profile["name"])
                for index, profile in enumerate(parents())}

DAILY_PROMPT = """\
Du er FamilyBot, en familieassistent for {family_context}.
Skriv en kort, vennlig morgenbriefing på norsk basert på dataene under.

Retningslinjer:
- Sikt mot 15 linjer, men ikke utelat viktige oppgaver eller svarfrister for å nå dette
- Ingen emojis, ingen markdown-overskrifter
- Naturlig, direkte språk — ikke stivt eller formelt
- Inkluder bare seksjoner som har innhold (utelat tomme seksjoner helt)
- Strukturer slik: dato + vær → hva skjer i dag → kommende dager → kanban (hvis noe) → RSVP (hvis noe)
Data-seksjoner som alltid skal med:
- Vær + luft + pollen: slå sammen til én linje. Format: "[værbeskrivelse], [min]–[max]°C. Luft: [aqi-label]. Pollen: [type nivå, type nivå]." Eksempel: "Sol, 6–15°C. Luft: God. Pollen: Bjørk kraftig, Salix moderat." Hvis et felt er 'ukjent', ta det med sånn: 'Luft: ukjent'.
- Klær: bruk weather.clothing_advice ordrett; den gjelder barnas dag fram til ca. 19. Hvis weather.evening_note finnes, ta den med som en separat kort kveldsadvarsel.
- T-bane (tbane): familien bruker {transport_context}. Ta status med i morgenrapporten og beskriv avvik kort.
- Sekundær lokasjon: hvis cabin_weather ikke er null, ta med helgevarsel for {cabin_context}.
- Ukeplaner: ta med korte, praktiske punkter for barna hvis ukeplaner finnes (lekser, ta med, viktige beskjeder). Bruk alltid barnets konfigurerte navn, aldri interne nøkler som child_1. Fullfør setningene. Hvis en mangler, ikke nevn det i morgenbriefingen.
- For kanban: bare vis must-do og important, ikke nice-to med mindre listen er tom
- Gjengi titlene på alle must-do/important-oppgaver og RSVP-er ordrett.
- Hvis det er en fridag, nevn det kort øverst
- Avslutt IKKE med "Ha en fin dag" eller lignende fraser
- Ukeplanens member_name, week_number og year er autoritative metadata. Ignorer utdaterte navn/ukeoverskrifter i raw_text.

DATA:
{data}
"""

WEEKLY_PROMPT = """\
Du er FamilyBot, en familieassistent for {family_context}.
Skriv en ukeoversikt på norsk basert på dataene under. Dette er søndagsoppsummeringen som sendes til begge foreldrene.

Retningslinjer:
- Naturlig, varm tone — dette er en helgeoppdatering
- Ingen emojis, ingen markdown-overskrifter med #
- Bruk linjeskift mellom seksjoner for lesbarhet
- Ukeplaner: oppsummer de viktigste tingene for hver unge (lekser, ta med, beskjeder)
- Hvis en ukeplan mangler, nevn det kort og bruk barnets konfigurerte navn
- Dager uten noe å si kan utelates
- For kanban: ta med alle must-do og important, og gjengi titlene ordrett
- Gjengi RSVP-titler ordrett.
- RSVP: vis tydelig hvis noe krever svar
- Avslutt med én setning om uken som venter — naturlig, ikke klisjé
- Bruk alltid member_name fra ukeplanen. Dens week_number og year gjelder selv om raw_text har en utdatert overskrift.

DATA:
{data}
"""


OPENCLAW = "/opt/homebrew/bin/openclaw"
OPENCLAW_MODEL = os.environ.get("FAMILYBOT_BRIEFING_MODEL", "openai/gpt-5.6-sol")
VACATION_MODE_FILE = str(workspace_path() / "memory" / "vacation-mode.json")


def vacation_mode_active() -> bool:
    try:
        with open(VACATION_MODE_FILE) as f:
            data = json.load(f)
        return bool(data.get("enabled"))
    except Exception:
        return False


def generate_text(prompt: str) -> str:
    """
    Generate briefing text via the OpenClaw Codex/OpenAI runtime.
    """
    if not OPENCLAW_MODEL.startswith("openai/"):
        return ""
    try:
        result = subprocess.run(
            [
                OPENCLAW,
                "agent",
                "--agent",
                "main",
                "--model",
                OPENCLAW_MODEL,
                "--thinking",
                "low",
                "--message",
                prompt,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, OSError):
        print("[briefing] OpenClaw agent unavailable")
        return ""
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            payloads = data.get("result", {}).get("payloads", [])
            if payloads:
                return "\n\n".join(p["text"].strip() for p in payloads
                                   if isinstance(p.get("text"), str) and p["text"].strip())
        except Exception:
            pass
    else:
        print("[briefing] OpenClaw agent failed")
    return ""


def render_daily_fallback(data: dict) -> str:
    lines = []
    weather = data.get("weather", {})
    aqi = data.get("aqi", {})
    pollen = data.get("pollen", [])
    pollen_text = ", ".join(f"{p.get('type')} {p.get('level')}" for p in pollen if p.get("type")) or "ukjent"
    lines.append(f"{data.get('date')}: {weather.get('summary', 'Vær ukjent')}. Luft: {aqi.get('label', 'ukjent')}. Pollen: {pollen_text}.")
    if weather.get("clothing_advice"):
        lines.append(f"Klær: {weather['clothing_advice']}")
    if weather.get("evening_note"):
        lines.append(f"Kveld: {weather['evening_note']}")
    if data.get("holiday"):
        lines.append(str(data["holiday"]))
    for forecast in data.get("cabin_weather") or []:
        lines.append(f"{CABIN_CONTEXT}: {forecast}")
    for item in data.get("tbane", []):
        lines.append(f"T-bane linje {item.get('line')}: {item.get('summary')}")

    today = data.get("today", {})
    for ev in today.get("events", []):
        title = ev.get("title")
        member = ev.get("member")
        time = ev.get("time")
        lines.append(f"I dag: {member + ' - ' if member else ''}{title}{' kl. ' + time if time else ''}")
    for rec in today.get("recurring", []):
        lines.append(f"I dag: {rec.get('member')} - {rec.get('activity')}. {rec.get('notes') or ''}".strip())

    plans = data.get("ukeplaner", {})
    for child, plan in plans.items():
        if plan and (plan.get("raw_text") or plan.get("summary")):
            lines.append(f"Ukeplan {CHILD_NAMES.get(child, child)}: {plan.get('raw_text') or plan['summary']}")

    lines.extend(action_lines(data))
    return "\n".join(lines)


def action_lines(data):
    lines = []
    for day in data.get("upcoming", []):
        for event in day.get("events", []):
            lines.append(f"{day.get('date')}: {event.get('member') or ''} {event.get('title') or ''}".strip())
        for event in day.get("recurring", []):
            lines.append(f"{day.get('date')}: {event.get('member') or ''} {event.get('activity') or ''}".strip())
    for parent, items in data.get("kanban", {}).items():
        for item in items:
            if item.get("priority") in {"must-do", "important"}:
                lines.append(f"Oppgaver {PARENT_NAMES.get(parent, parent)}: {item.get('title')}")
    for item in data.get("pending_rsvp", []):
        lines.append(f"Svar ønskes: {item.get('member') or ''} {item.get('title')} {item.get('date') or ''}".strip())
    return lines


def render_weekly_fallback(data: dict) -> str:
    lines = [f"Uke {data.get('week')}: {data.get('week_start')} til {data.get('week_end')}."]
    for day in data.get("days", []):
        bits = []
        if day.get("holiday"):
            bits.append(day["holiday"])
        bits += [f"{e.get('member') + ': ' if e.get('member') else ''}{e['title']}"
                 for e in day.get("events", []) if e.get("title")]
        bits += [f"{r.get('member')}: {r.get('activity')}" for r in day.get("recurring", [])]
        if bits:
            lines.append(f"{day.get('date')}: " + "; ".join(bits))
    for child, plan in data.get("ukeplaner", {}).items():
        if plan and (plan.get("raw_text") or plan.get("summary")):
            lines.append(f"Ukeplan {CHILD_NAMES.get(child, child)}: {plan.get('raw_text') or plan['summary']}")
        else:
            lines.append(f"Ukeplan for {CHILD_NAMES.get(child, child)} er ikke mottatt ennå.")
    lines.extend(action_lines(data))
    return "\n".join(lines)


def message_parts(text: str) -> list[str]:
    """Lossless parts, at most 3600 UTF-16 units even for all-emoji input."""
    parts = []
    while len(text) > 1800:
        boundary = max(text.rfind("\n", 0, 1800), text.rfind(" ", 0, 1800))
        end = boundary + 1 if boundary >= 900 else 1800
        parts.append(text[:end])
        text = text[end:]
    if text:
        parts.append(text)
    return parts


def send_telegram(target: str, message: str) -> bool:
    """Perform one direct Telegram attempt.

    Durability and retries live in DeliveryOutbox.  This function intentionally
    reports vacation mode as *not sent* so skipped delivery can never be logged
    as success.
    """
    if vacation_mode_active():
        print("[briefing] Vacation mode active; Telegram send blocked.")
        return False
    result = subprocess.run(
        [OPENCLAW, "message", "send",
         "--channel", "telegram",
         "--target", target,
         "--message", message],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[:300]
        print(f"[briefing] Telegram delivery failed for {target}: {detail}")
        return False
    return True


def deliver_briefing(kind: str, text: str, now: Optional[datetime] = None) -> bool:
    """Queue both parent deliveries first, then attempt all due messages."""
    if not text.strip():
        raise ValueError("Refusing to queue an empty briefing")
    if vacation_mode_active():
        print("[briefing] Vacation mode active; briefing was generated but not queued.")
        return True

    current = now or datetime.now(OSLO)
    if kind == "daily":
        period = current.date().isoformat()
        expires_at = current + timedelta(hours=8)
    elif kind == "weekly":
        iso = current.isocalendar()
        period = f"{iso.year}-W{iso.week:02d}"
        expires_at = current + timedelta(days=2)
    else:
        raise ValueError(f"Unknown briefing kind: {kind}")

    outbox = DeliveryOutbox(database_path())
    parts = message_parts(text)
    for name, target in RECIPIENTS:
        key = f"briefing:{kind}:{period}:{target}"
        outbox.enqueue_parts(
            idempotency_key=key, target=target,
            parts=[part if len(parts) == 1 else f"({index}/{len(parts)})\n{part}"
                   for index, part in enumerate(parts, start=1)],
            kind=f"briefing-{kind}", expires_at=expires_at,
        )
        print(f"  Queued {kind} for {name}")

    result = outbox.deliver_pending(send_telegram)
    counts = outbox.counts()
    print(
        f"[briefing] Delivery result: sent={result.sent}, failed={result.failed}, "
        f"expired={result.expired}, pending={counts['pending']}"
    )
    return result.ok and counts["pending"] == 0 and counts["sending"] == 0


def valid_briefing(text, data):
    """Reject structural defects; this is not a semantic completeness proof."""
    if not text.strip() or re.search(r"\b(?:child|parent)_\d+\b", text, re.I):
        return False
    for child, plan in data.get("ukeplaner", {}).items():
        if plan and CHILD_NAMES.get(child, child).casefold() not in text.casefold():
            return False
    # Exact action titles prevent important tasks/RSVPs disappearing in prose.
    required = [item["title"] for items in data.get("kanban", {}).values()
                for item in items if item.get("title") and item.get("priority") in {"must-do", "important"}]
    required += [item["title"] for item in data.get("pending_rsvp", []) if item.get("title")]
    if any(title.casefold() not in text.casefold() for title in required):
        return False
    return True


def select_briefing(kind, text, data, render):
    fallback = not valid_briefing(text, data)
    if fallback:
        text = render(data)
    try:
        record_briefing(kind, fallback)
    except OSError:
        # Observability failure must never prevent durable delivery.
        print("[briefing] Unable to persist quality observation")
    return text


def run_daily():
    data = collect_daily()
    prompt = DAILY_PROMPT.format(family_context=FAMILY_CONTEXT, transport_context=TRANSPORT_CONTEXT, cabin_context=CABIN_CONTEXT, data=json.dumps(data, ensure_ascii=False, indent=2))
    text = generate_text(prompt)
    text = select_briefing("daily", text, data, render_daily_fallback)
    return deliver_briefing("daily", text)


def run_weekly():
    data = collect_weekly()
    prompt = WEEKLY_PROMPT.format(family_context=FAMILY_CONTEXT, data=json.dumps(data, ensure_ascii=False, indent=2))
    text = generate_text(prompt)
    text = select_briefing("weekly", text, data, render_weekly_fallback)
    return deliver_briefing("weekly", text)


def run_preview():
    from datetime import date

    print("=== DAILY DATA ===")
    daily = collect_daily()
    print(json.dumps(daily, ensure_ascii=False, indent=2))

    print("\n=== WEEKLY DATA ===")
    weekly = collect_weekly()
    print(json.dumps(weekly, ensure_ascii=False, indent=2))

    print("\n=== DAILY PROMPT (first 300 chars) ===")
    prompt = DAILY_PROMPT.format(family_context=FAMILY_CONTEXT, transport_context=TRANSPORT_CONTEXT, cabin_context=CABIN_CONTEXT, data=json.dumps(daily, ensure_ascii=False))
    print(prompt[:300] + "...")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    now = datetime.now(OSLO).strftime("%H:%M")
    print(f"[{now}] Briefing mode: {mode}")

    if mode == "daily":
        if not run_daily():
            sys.exit(2)
    elif mode == "weekly":
        if not run_weekly():
            sys.exit(2)
    elif mode == "preview":
        run_preview()
    else:
        print(f"Unknown mode: {mode}. Use daily / weekly / preview")
        sys.exit(1)
