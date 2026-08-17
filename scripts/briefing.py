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
import subprocess
from datetime import datetime, timedelta
from typing import Optional
import zoneinfo

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")

sys.path.insert(0, os.path.dirname(__file__))
from briefing_data import collect_daily, collect_weekly
from family_config import family_prompt_context, integration, telegram_recipients
from reliability import DeliveryOutbox, database_path, workspace_path

RECIPIENTS = telegram_recipients()
FAMILY_CONTEXT = family_prompt_context()
TRANSPORT_CONTEXT = str(integration("transport").get("route_description") or "konfigurert strekning")
CABIN_CONTEXT = str(integration("weather").get("cabin_label") or "sekundær lokasjon")

DAILY_PROMPT = """\
Du er FamilyBot, en familieassistent for {family_context}.
Skriv en kort, vennlig morgenbriefing på norsk basert på dataene under.

Retningslinjer:
- Maks 15 linjer totalt
- Ingen emojis, ingen markdown-overskrifter
- Naturlig, direkte språk — ikke stivt eller formelt
- Inkluder bare seksjoner som har innhold (utelat tomme seksjoner helt)
- Strukturer slik: dato + vær → hva skjer i dag → kommende dager → kanban (hvis noe) → RSVP (hvis noe)
Data-seksjoner som alltid skal med:
- Vær + luft + pollen: slå sammen til én linje. Format: "[værbeskrivelse], [min]–[max]°C. Luft: [aqi-label]. Pollen: [type nivå, type nivå]." Eksempel: "Sol, 6–15°C. Luft: God. Pollen: Bjørk kraftig, Salix moderat." Hvis et felt er 'ukjent', ta det med sånn: 'Luft: ukjent'.
- Klær: bruk weather.clothing_advice ordrett; den gjelder barnas dag fram til ca. 19. Hvis weather.evening_note finnes, ta den med som en separat kort kveldsadvarsel.
- T-bane (tbane): familien bruker {transport_context}. Ta status med i morgenrapporten og beskriv avvik kort.
- Sekundær lokasjon: hvis cabin_weather ikke er null, ta med helgevarsel for {cabin_context}.
- Ukeplaner: ta med korte, praktiske punkter for barna hvis ukeplaner finnes (lekser, ta med, viktige beskjeder). Hvis en mangler, ikke nevn det i morgenbriefingen.
- For kanban: bare vis must-do og important, ikke nice-to med mindre listen er tom
- Hvis det er en fridag, nevn det kort øverst
- Avslutt IKKE med "Ha en fin dag" eller lignende fraser

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
- For kanban: bare must-do og important, maks 3 per person
- RSVP: vis tydelig hvis noe krever svar
- Avslutt med én setning om uken som venter — naturlig, ikke klisjé

DATA:
{data}
"""


OPENCLAW = "/opt/homebrew/bin/openclaw"
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
    try:
        result = subprocess.run(
            [
                OPENCLAW,
                "agent",
                "--agent",
                "main",
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
    except subprocess.TimeoutExpired:
        print("[briefing] OpenClaw agent timed out")
        return ""
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            payloads = data.get("result", {}).get("payloads", [])
            if payloads:
                return payloads[0].get("text", "").strip()
        except Exception:
            pass
    else:
        print(f"[briefing] OpenClaw agent failed: {result.stderr[:200]}")
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
        if plan and plan.get("summary"):
            lines.append(f"Ukeplan {child.capitalize()}: {plan['summary'][:350]}")

    return "\n".join(lines[:15])


def render_weekly_fallback(data: dict) -> str:
    lines = [f"Uke {data.get('week')}: {data.get('week_start')} til {data.get('week_end')}."]
    for day in data.get("days", []):
        bits = []
        if day.get("holiday"):
            bits.append(day["holiday"])
        bits += [e.get("title", "") for e in day.get("events", []) if e.get("title")]
        bits += [f"{r.get('member')}: {r.get('activity')}" for r in day.get("recurring", [])]
        if bits:
            lines.append(f"{day.get('date')}: " + "; ".join(bits))
    for child, plan in data.get("ukeplaner", {}).items():
        if plan and plan.get("summary"):
            lines.append(f"Ukeplan {child.capitalize()}: {plan['summary'][:500]}")
        else:
            lines.append(f"{child.capitalize()}s ukeplan er ikke mottatt ennå.")
    return "\n".join(lines)


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
    for name, target in RECIPIENTS:
        key = f"briefing:{kind}:{period}:{target}"
        outbox.enqueue(
            idempotency_key=key,
            target=target,
            payload=text,
            kind=f"briefing-{kind}",
            expires_at=expires_at,
        )
        print(f"  Queued {kind} for {name}")

    result = outbox.deliver_pending(send_telegram)
    counts = outbox.counts()
    print(
        f"[briefing] Delivery result: sent={result.sent}, failed={result.failed}, "
        f"expired={result.expired}, pending={counts['pending']}"
    )
    return result.ok and counts["pending"] == 0 and counts["sending"] == 0


def run_daily():
    data = collect_daily()
    prompt = DAILY_PROMPT.format(family_context=FAMILY_CONTEXT, transport_context=TRANSPORT_CONTEXT, cabin_context=CABIN_CONTEXT, data=json.dumps(data, ensure_ascii=False, indent=2))
    text = generate_text(prompt)
    if not text:
        print("LLM returned empty response; using fallback.")
        text = render_daily_fallback(data)
    return deliver_briefing("daily", text)


def run_weekly():
    data = collect_weekly()
    prompt = WEEKLY_PROMPT.format(family_context=FAMILY_CONTEXT, data=json.dumps(data, ensure_ascii=False, indent=2))
    text = generate_text(prompt)
    if not text:
        print("LLM returned empty response; using fallback.")
        text = render_weekly_fallback(data)
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
