#!/usr/bin/env python3
"""
Collects all relevant data for a briefing period and returns it as a
structured dict. The actual text generation is done by the LLM.
"""

import sqlite3
import subprocess
import json as _json
import os
import sys
from datetime import date, datetime, timedelta
import zoneinfo

sys.path.insert(0, os.path.dirname(__file__))
from reliability import connect_db, database_path
from family_config import children, integration, member_names, parents

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
DB_PATH = str(database_path())

DAYS_NO = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MONTHS_NO = ["januar", "februar", "mars", "april", "mai", "juni",
             "juli", "august", "september", "oktober", "november", "desember"]
MEMBER_NAMES = member_names()
PARENT_PROFILES = parents()
CHILD_PROFILES = children()
ENTUR_CLIENT = str(integration("entur").get("client_name") or "familybot-local")
WEATHER_USER_AGENT = str(integration("weather").get("user_agent") or "FamilyBot-local/1.0")
WEATHER_CONFIG = integration("weather")
HOME_LAT = float(WEATHER_CONFIG.get("home_lat") or 0)
HOME_LON = float(WEATHER_CONFIG.get("home_lon") or 0)
CABIN_LABEL = str(WEATHER_CONFIG.get("cabin_label") or "")
CABIN_LAT = float(WEATHER_CONFIG.get("cabin_lat") or 0)
CABIN_LON = float(WEATHER_CONFIG.get("cabin_lon") or 0)

# Legacy hardcoded recurring — kept for fallback
# Primary source is now the activities table in the DB (see recurring_for_date)
RECURRING_LEGACY = {}

DAY_NAME_TO_ISOWEEKDAY = {
    "mandag": 1, "tirsdag": 2, "onsdag": 3, "torsdag": 4,
    "fredag": 5, "lørdag": 6, "søndag": 7,
    "mandager": 1, "tirsdager": 2, "onsdager": 3, "torsdager": 4,
    "fredager": 5, "lørdager": 6, "søndager": 7,
}


def db():
    return connect_db(DB_PATH)


def fmt_date(d: date) -> str:
    return f"{DAYS_NO[d.isoweekday()-1]} {d.day}. {MONTHS_NO[d.month-1]}"


def is_school_day(d: date, c) -> bool:
    if d.isoweekday() > 5:
        return False
    return not c.execute(
        "SELECT 1 FROM norwegian_holidays WHERE date=?", (d.isoformat(),)
    ).fetchone()


def holiday_name(d: date, c):
    row = c.execute(
        "SELECT name FROM norwegian_holidays WHERE date=?", (d.isoformat(),)
    ).fetchone()
    return row[0] if row else None


def events_for_date(d: date, c) -> list:
    rows = c.execute("""
        SELECT ce.title, ce.event_time, ce.member_id, ce.bring,
               ce.description, ce.requires_response, ce.location, ce.source
        FROM calendar_events ce WHERE ce.event_date=?
        ORDER BY ce.event_time NULLS LAST
    """, (d.isoformat(),)).fetchall()
    return [
        {"title": r[0], "time": r[1], "member": MEMBER_NAMES.get(r[2]),
         "bring": r[3], "description": r[4], "requires_response": bool(r[5]),
         "location": r[6], "source": r[7]}
        for r in rows
    ]


def recurring_for_date(d: date) -> list:
    result = []
    target_dow = d.isoweekday()  # 1=Monday ... 7=Sunday

    # Primary: load from activities table in DB
    try:
        conn = db()
        c = conn.cursor()
        rows = c.execute("""
            SELECT member_id, name, schedule, notes
            FROM activities
            WHERE active=1
              AND (paused_until IS NULL OR paused_until < ?)
        """, (d.isoformat(),)).fetchall()
        conn.close()
        week_num = d.isocalendar()[1]
        for member_id, name, schedule, notes in rows:
            if not schedule:
                continue
            sched_lower = schedule.lower()
            # Detect annenhver-uke pattern
            every_other = "annenhver" in sched_lower or "annenhver" in (notes or "").lower()
            odd_weeks = "odde" in sched_lower or "odde" in (notes or "").lower()
            even_weeks = "part" in sched_lower or "part" in (notes or "").lower()
            if every_other:
                if odd_weeks and week_num % 2 == 0:
                    continue  # This week is even, skip
                if even_weeks and week_num % 2 == 1:
                    continue  # This week is odd, skip
            for token in sched_lower.replace(',', ' ').split():
                dow = DAY_NAME_TO_ISOWEEKDAY.get(token)
                if dow == target_dow:
                    entry = {"member": MEMBER_NAMES.get(member_id, "?"), "activity": name}
                    if notes:
                        entry["notes"] = notes
                    result.append(entry)
                    break
    except Exception:
        # Fallback to legacy hardcoded if DB fails
        for member_id, schedule in RECURRING_LEGACY.items():
            for day, time, name in schedule:
                if day == target_dow:
                    result.append({"member": MEMBER_NAMES[member_id], "time": time, "activity": name})

    return result


def fetch_tbane_status() -> list:
    """
    Read T-bane status from cached status file (written by tbane_monitor.py every 15 min).
    Returns list of dicts with {line, summary} for active issues, or [{"line": "2", "summary": "normal drift"}] if clear.
    Falls back to live fetch if cache is missing.
    """
    # Always fetch live at briefing time — this is a point-in-time snapshot
    try:
        import re as _re
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             "-H", f"ET-Client-Name: {ENTUR_CLIENT}",
             "https://api.entur.io/realtime/v1/rest/sx?datasetId=RUT"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 or not r.stdout.strip():
            return [{"line": "2", "summary": "status ukjent"}]

        data = r.stdout
        TBANE_LINE2 = {'2'}
        ALL_TBANE = {'1', '2', '3', '4', '5', '6'}
        SKIP = ('forsinkels', 'delay', 'noe forsinket', 'minor delay',
                'ikke egnet for rullestol', 'not suitable for wheelchair')

        situations = _re.findall(r'<PtSituationElement>(.*?)</PtSituationElement>', data, _re.DOTALL)
        issues = []
        seen = set()

        for sit in situations:
            lines = set(_re.findall(r'<LineRef>RUT:Line:(\d+)</LineRef>', sit))
            summaries_no = _re.findall(r'<Summary[^>]*lang=["\'\']NO["\'\'][^>]*>([^<]+)</Summary>', sit)
            if not summaries_no:
                all_sum = _re.findall(r'<Summary>([^<]+)</Summary>', sit)
                summaries_no = all_sum[::2] if len(all_sum) > 1 else all_sum
            summary = summaries_no[0].strip() if summaries_no else None
            if not summary or any(kw in summary.lower() for kw in SKIP):
                continue
            tbane = lines & ALL_TBANE
            if not tbane:
                continue
            if len(tbane) >= 4:
                key = ("all", summary[:40])
                if key not in seen:
                    seen.add(key)
                    issues.append({"line": "alle linjer", "summary": summary})
            elif tbane & TBANE_LINE2:
                key = ("2", summary[:40])
                if key not in seen:
                    seen.add(key)
                    issues.append({"line": "2", "summary": summary})

        return issues if issues else [{"line": "2", "summary": "normal drift"}]
    except Exception:
        return [{"line": "2", "summary": "status ukjent"}]

def fetch_met_data(target_date) -> dict:
    """
    Fetch weather, air quality and pollen for the configured home area.
    All fields always populated — shows 'ukjent' on failure so caller knows API ran.

    Sources:
    - api.met.no/locationforecast (weather)
    - api.met.no/airqualityforecast (AQI)
    - yr.no pollen API (NAAF data)
    Coordinates are read exclusively from local family configuration.
    """
    LAT, LON = HOME_LAT, HOME_LON
    result = {
        "weather": {"summary": "ukjent", "max_c": None, "min_c": None, "desc": "ukjent", "rain_mm": 0,
                    "hazards": [], "hazard_time": None, "evening_note": None,
                    "clothing_advice": "Sjekk værvarselet før dere går."},
        "aqi": {"value": None, "label": "ukjent"},
        "pollen": [{"type": "ukjent", "level": "ukjent"}],
    }

    # --- Weather ---
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             "-H", f"User-Agent: {WEATHER_USER_AGENT}",
             f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={LAT}&lon={LON}"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            wdata = _json.loads(r.stdout)
            series = wdata["properties"]["timeseries"]
            def local_dt(entry):
                return datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(OSLO)

            # MET timestamps are UTC. Select by Oslo calendar date and inspect the
            # full day. Clothing is calculated for the children's likely outdoor
            # window (06:00–19:00); later hazards are reported separately.
            day_entries = [t for t in series if local_dt(t).date() == target_date]
            if day_entries:
                temps = [t["data"]["instant"]["details"]["air_temperature"] for t in day_entries]
                winds = [t["data"]["instant"]["details"].get("wind_speed", 0) for t in day_entries]
                precips = [t["data"].get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0) for t in day_entries]
                symbols = [t["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "").lower() for t in day_entries]
                morning = next((t for t in day_entries if 6 <= local_dt(t).hour <= 8), day_entries[0])
                morning_symbol = morning["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "").lower()
                SYMBOLS = {
                    "clearsky": "Sol", "fair": "Lettskyet", "partlycloudy": "Delvis skyet",
                    "cloudy": "Overskyet", "fog": "Tåke", "lightrain": "Lett regn",
                    "rain": "Regn", "heavyrain": "Kraftig regn", "lightsnow": "Lett snø",
                    "snow": "Snø", "sleet": "Sludd", "rainshowers": "Regnbyger",
                    "snowshowers": "Snøbyger", "thunder": "Tordenbyger",
                }
                morning_desc = next((v for k, v in SYMBOLS.items() if k in morning_symbol), morning_symbol or "Ukjent")
                hazards = []
                hazard_match = None
                for key, label in (("thunder", "torden"), ("heavyrain", "kraftig regn"),
                                   ("snow", "snø"), ("sleet", "sludd"), ("rain", "regn")):
                    match = next(((entry, symbol) for entry, symbol in zip(day_entries, symbols) if key in symbol), None)
                    if match:
                        hazards.append(label)
                        if hazard_match is None:
                            hazard_match = match
                max_wind = max(winds) if winds else 0
                if max_wind >= 10:
                    hazards.append("kraftig vind")
                total_rain = sum(precips)
                peak_rain = max(precips) if precips else 0
                hazard_time = local_dt(hazard_match[0]).strftime("%H:%M") if hazard_match else None

                kid_entries = [t for t in day_entries if 6 <= local_dt(t).hour < 19]
                kid_symbols = [t["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "").lower() for t in kid_entries]
                kid_precips = [t["data"].get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0) for t in kid_entries]
                kid_temps = [t["data"]["instant"]["details"]["air_temperature"] for t in kid_entries] or temps
                kid_winds = [t["data"]["instant"]["details"].get("wind_speed", 0) for t in kid_entries]
                kid_thunder = any("thunder" in symbol for symbol in kid_symbols)
                kid_heavy_rain = any("heavyrain" in symbol for symbol in kid_symbols) or (max(kid_precips or [0]) >= 3)
                kid_rain = sum(kid_precips) > 0.5
                kid_windy = max(kid_winds or [0]) >= 10

                if "torden" in hazards:
                    desc = "Tordenbyger" + (f" fra ca. {hazard_time}" if hazard_time else "")
                elif "kraftig regn" in hazards or peak_rain >= 3:
                    desc = "Kraftig regn" + (f" fra ca. {hazard_time}" if hazard_time else "")
                elif total_rain > 0.5:
                    desc = morning_desc + ", regn senere"
                else:
                    desc = morning_desc

                if kid_thunder:
                    clothing = "Vanntett jakke og sko; barna bør være inne når tordenværet kommer."
                elif kid_heavy_rain:
                    clothing = "Regnjakke og vanntette sko; en tynn jakke alene er ikke nok."
                elif kid_rain:
                    clothing = "Ta med regnjakke og sko som tåler regn."
                elif min(kid_temps) < 10:
                    clothing = "Kle dere lagvis for en kjølig morgen."
                elif min(kid_temps) < 15:
                    clothing = "En lett jakke kan være nyttig tidlig og sent."
                else:
                    clothing = "Lette klær passer; ta med et tynt lag til ettermiddagen."
                if kid_windy and "vind" not in clothing.lower():
                    clothing += " Velg også et vindtett ytterlag."

                first_hazard_hour = local_dt(hazard_match[0]).hour if hazard_match else None
                evening_note = None
                if first_hazard_hour is not None and first_hazard_hour >= 19:
                    evening_note = f"Kveldsvarsel: {hazards[0]} fra ca. {hazard_time}; dette påvirker ikke nødvendigvis barnas klær tidligere på dagen."

                result["weather"] = {
                    "summary": f"{desc}, {int(min(temps))}–{int(max(temps))}°C" + (f", {total_rain:.1f}mm nedbør" if total_rain > 0.5 else ""),
                    "max_c": int(max(temps)), "min_c": int(min(temps)),
                    "desc": desc, "rain_mm": round(total_rain, 1),
                    "hazards": hazards, "hazard_time": hazard_time,
                    "peak_hourly_rain_mm": round(peak_rain, 1), "max_wind_mps": round(max_wind, 1),
                    "clothing_advice": clothing, "evening_note": evening_note,
                }
    except Exception as e:
        result["weather"]["summary"] = f"ukjent ({e})"

    # --- Air quality ---
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             "-H", f"User-Agent: {WEATHER_USER_AGENT}",
             f"https://api.met.no/weatherapi/airqualityforecast/0.1/?lat={LAT}&lon={LON}"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            aqdata = _json.loads(r.stdout)
            target_iso = target_date.isoformat()
            day_entries = [t for t in aqdata["data"]["time"] if t["from"].startswith(target_iso)]
            morning = next((t for t in day_entries if any(h in t["from"] for h in ["T06:", "T07:", "T08:"])), day_entries[0] if day_entries else None)
            if morning:
                aqi_val = morning["variables"].get("AQI", {}).get("value")
                if aqi_val is not None:
                    aqi_int = int(round(aqi_val))
                    AQI_LABELS = {1: "Sv\u00e6rt god", 2: "God", 3: "Moderat", 4: "D\u00e5rlig", 5: "Sv\u00e6rt d\u00e5rlig"}
                    result["aqi"] = {"value": aqi_int, "label": AQI_LABELS.get(aqi_int, str(aqi_int))}
    except Exception as e:
        result["aqi"]["label"] = f"ukjent ({e})"

    # --- Pollen ---
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             "-H", f"User-Agent: {WEATHER_USER_AGENT}",
             "https://www.yr.no/api/v0/locations/1-72837/pollen"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            pdata = _json.loads(r.stdout)
            target_iso = target_date.isoformat()
            forecasts = pdata.get("_embedded", {}).get("pollenForecast", [])
            today_f = next((f for f in forecasts if f["date"].startswith(target_iso)), None)
            if today_f:
                items = []
                for level_data in today_f.get("distributions", {}).values():
                    level_name = level_data.get("distributionName", "?")
                    for pt in level_data.get("pollenTypes", []):
                        items.append({"type": pt["name"], "level": level_name})
                result["pollen"] = items if items else [{"type": "ingen", "level": "ingen registrert"}]
            else:
                result["pollen"] = [{"type": "ingen data", "level": "ikke tilgjengelig"}]
    except Exception as e:
        result["pollen"] = [{"type": "ukjent", "level": str(e)}]

    return result


def fetch_weather(target_date) -> dict:
    """Backward compat — returns weather portion of fetch_met_data."""
    return fetch_met_data(target_date)["weather"]


def pending_rsvp(c) -> list:
    rows = c.execute("""
        SELECT title, event_date, group_name, member_id
        FROM spond_events
        WHERE requires_response=1 AND event_date >= date('now')
        ORDER BY event_date LIMIT 5
    """).fetchall()
    return [{"title": r[0], "date": r[1], "group": r[2],
             "member": MEMBER_NAMES.get(r[3])} for r in rows]


def week_plan(member_id: int, week: int, year: int, c):
    row = c.execute("""
        SELECT summary, teacher, raw_text FROM week_plans
        WHERE member_id=? AND week_number=? AND year=?
        ORDER BY created_at DESC LIMIT 1
    """, (member_id, week, year)).fetchone()
    return {"summary": row[0], "teacher": row[1], "raw_text": row[2]} if row else None


def kanban_items(assigned_to: str, c) -> list:
    rows = c.execute("""
        SELECT title, priority, due_date, description
        FROM kanban_cards
        WHERE lane != 'done' AND archived_at IS NULL
          AND (assigned_to=? OR assigned_to='both')
        ORDER BY CASE priority
            WHEN 'must-do' THEN 1
            WHEN 'important' THEN 2
            ELSE 3 END, due_date NULLS LAST
        LIMIT 5
    """, (assigned_to,)).fetchall()
    return [{"title": r[0], "priority": r[1], "due": r[2], "description": r[3]}
            for r in rows]


# ── PUBLIC FUNCTIONS ───────────────────────────────────────────────────────────

def collect_daily(today: date = None) -> dict:
    if today is None:
        today = datetime.now(OSLO).date()

    conn = db()
    c = conn.cursor()

    iso_week = today.isocalendar().week
    school = is_school_day(today, c)
    holiday = holiday_name(today, c)

    # Today
    today_events = events_for_date(today, c)
    today_recurring = recurring_for_date(today)

    # Next 2 weekdays
    upcoming = []
    d = today + timedelta(days=1)
    count = 0
    while count < 2:
        if d.isoweekday() <= 5:
            day_data = {
                "date": fmt_date(d),
                "iso_date": d.isoformat(),
                "school_day": is_school_day(d, c),
                "holiday": holiday_name(d, c),
                "events": events_for_date(d, c),
                "recurring": recurring_for_date(d),
            }
            if day_data["events"] or day_data["recurring"] or day_data["holiday"]:
                upcoming.append(day_data)
            count += 1
        d += timedelta(days=1)

    # Kanban
    kanban = {
        str(profile.get("slug") or f"parent_{index + 1}"): kanban_items(str(profile["name"]).lower(), c)
        for index, profile in enumerate(PARENT_PROFILES)
    }

    rsvps = pending_rsvp(c)
    # On the weekend the actionable plan is the coming school week, not the
    # week that just ended.
    plan_date = today
    if today.isoweekday() >= 6:
        plan_date = today + timedelta(days=8 - today.isoweekday())
    plan_week = plan_date.isocalendar().week
    plan_year = plan_date.year
    plans = {
        str(profile.get("slug") or f"child_{index + 1}"): week_plan(int(profile["member_id"]), plan_week, plan_year, c)
        for index, profile in enumerate(CHILD_PROFILES)
    }
    conn.close()

    # All external data: weather + AQI + pollen via met.no/yr.no
    met = fetch_met_data(today)
    weather = met["weather"]
    aqi = met["aqi"]
    pollen = met["pollen"]

    # T-bane status
    tbane = fetch_tbane_status()

    # Optional second-location weekend weather — only on Thursdays, via met.no
    cabin_weather = None
    if today.isoweekday() == 4 and CABIN_LAT and CABIN_LON:  # Thursday
        try:
            from datetime import timedelta as _td
            r = subprocess.run(
                ["curl", "-s", "--max-time", "8",
                 "-H", f"User-Agent: {WEATHER_USER_AGENT}",
                 f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={CABIN_LAT}&lon={CABIN_LON}"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip():
                wdata = _json.loads(r.stdout)
                series = wdata["properties"]["timeseries"]
                weekend = []
                for offset, day_name in [(2, "Lørdag"), (3, "Søndag")]:
                    target_d = today + _td(days=offset)
                    day_entries = [t for t in series if t["time"].startswith(target_d.isoformat())]
                    if day_entries:
                        temps = [t["data"]["instant"]["details"]["air_temperature"] for t in day_entries]
                        precips = [t["data"].get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0) for t in day_entries]
                        morning = next((t for t in day_entries if any(h in t["time"] for h in ["T06:", "T07:", "T08:"])), day_entries[0])
                        symbol = morning["data"].get("next_1_hours", {}).get("summary", {}).get("symbol_code", "")
                        SYMBOLS = {"clearsky": "Sol", "fair": "Lettskyet", "partlycloudy": "Delvis skyet",
                                   "cloudy": "Overskyet", "lightsnow": "Lett snø", "snow": "Snø",
                                   "lightrain": "Lett regn", "rain": "Regn", "sleet": "Sludd"}
                        desc = next((v for k, v in SYMBOLS.items() if k in symbol.lower()), symbol or "Ukjent")
                        total_rain = sum(precips)
                        s = f"{day_name}: {desc}, {int(min(temps))}–{int(max(temps))}°C"
                        if total_rain > 0.5:
                            s += f", {total_rain:.1f}mm nedbør"
                        weekend.append(s)
                if weekend:
                    cabin_weather = weekend
        except Exception:
            pass

    return {
        "type": "daily",
        "date": fmt_date(today),
        "iso_date": today.isoformat(),
        "week": iso_week,
        "ukeplan_week": plan_week,
        "school_day": school,
        "holiday": holiday,
        "weather": weather,       # {summary, max_c, min_c, desc, rain_mm} — alltid satt
        "aqi": aqi,                 # {value 1–5, label} — luftkvalitet, alltid satt
        "pollen": pollen,           # [{type, level}] — alltid satt
        "tbane": tbane,             # [{line, summary}] — alltid satt (normal drift eller avvik)
        "cabin_weather": cabin_weather,
        "cabin_label": CABIN_LABEL,
        "today": {
            "events": today_events,
            "recurring": today_recurring,
        },
        "upcoming": upcoming,
        "kanban": kanban,
        "ukeplaner": plans,
        "pending_rsvp": rsvps,
    }


def collect_weekly(reference: date = None) -> dict:
    if reference is None:
        reference = datetime.now(OSLO).date()

    # Week start = next Monday (or tomorrow if today is Sunday)
    week_start = reference + timedelta(days=8 - reference.isoweekday())

    week_end = week_start + timedelta(days=4)
    iso_week = week_start.isocalendar().week
    year = week_start.year

    conn = db()
    c = conn.cursor()

    # Build day-by-day
    days = []
    for offset in range(5):
        d = week_start + timedelta(days=offset)
        days.append({
            "date": fmt_date(d),
            "iso_date": d.isoformat(),
            "school_day": is_school_day(d, c),
            "holiday": holiday_name(d, c),
            "events": events_for_date(d, c),
            "recurring": recurring_for_date(d),
        })

    plans = {
        str(profile.get("slug") or f"child_{index + 1}"): week_plan(int(profile["member_id"]), iso_week, year, c)
        for index, profile in enumerate(CHILD_PROFILES)
    }

    kanban = {
        str(profile.get("slug") or f"parent_{index + 1}"): kanban_items(str(profile["name"]).lower(), c)
        for index, profile in enumerate(PARENT_PROFILES)
    }
    rsvps = pending_rsvp(c)

    conn.close()

    return {
        "type": "weekly",
        "week": iso_week,
        "year": year,
        "week_start": fmt_date(week_start),
        "week_end": fmt_date(week_end),
        "days": days,
        "ukeplaner": plans,
        "kanban": kanban,
        "pending_rsvp": rsvps,
    }
