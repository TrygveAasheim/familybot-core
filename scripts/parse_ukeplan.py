#!/usr/bin/env python3
"""
Parser for Oslo skole ukeplaner (PDF).

Kolonnestruktur i timeplanen (side 2):
Venstre margin (time/klokkeslett) | Mandag | Tirsdag | Onsdag | Torsdag | Fredag

Kolonnebredden er jevn. X-posisjoner til aktivitetsinnhold identifiserer dag:
- Mandag:  x ≈ 200-295
- Tirsdag: x ≈ 295-400
- Onsdag:  x ≈ 400-510
- Torsdag: x ≈ 510-615
- Fredag:  x ≈ 615+

Disse grensene er basert på observasjon av PDF-koordinater og er konsistente
på tvers av ukeplaner fra samme skole/lærer.
"""

import re
import pdfplumber
from datetime import date
from typing import Optional


MONTHS_NO = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12
}

# Column boundaries are now computed dynamically from day header positions in each PDF.
# See _compute_col_boundaries(). These defaults are only used as fallback.
COL_BOUNDARIES_DEFAULT = [254, 355, 462, 569]
COL_INDEX_TO_WEEKDAY = {0: "mandag", 1: "tirsdag", 2: "onsdag", 3: "torsdag", 4: "fredag"}


def _compute_col_boundaries(words: list) -> list:
    """
    Compute column boundaries dynamically from day header x-positions.
    Returns list of 4 boundary x-values splitting [Man|Tir, Tir|Ons, Ons|Tor, Tor|Fre].
    Falls back to defaults if headers not found.
    """
    DAYS = ['mandag', 'tirsdag', 'onsdag', 'torsdag', 'fredag']
    centers = {}
    for w in words:
        d = w['text'].lower()
        if d in DAYS and d not in centers:
            centers[d] = (w['x0'] + w['x1']) / 2

    if len(centers) < 4:
        return COL_BOUNDARIES_DEFAULT

    ordered = [centers.get(d) for d in DAYS if centers.get(d) is not None]
    ordered.sort()

    if len(ordered) < 2:
        return COL_BOUNDARIES_DEFAULT

    # Boundaries = midpoints between consecutive column centers
    boundaries = [(ordered[i] + ordered[i+1]) / 2 for i in range(len(ordered)-1)]
    return boundaries

ACTIVITY_KEYWORDS = [
    "besøk", "forfatterbesøk", "kick", "rydde", "loppemarked", "marsjøvelse",
    "dks", "rådhuset", "tur", "konsert", "uteklasse", "svømming", "bursdag",
    "prøve", "innlevering", "hagedag", "litteraturhuset", "uteskole", "avspaserer",
    "skole", "møte", "overnatting", "utflukt"
]


def x_to_weekday_index(x: float, boundaries: list = None) -> int:
    """Map an x-coordinate to a weekday column index (0=Mon, 4=Fri)."""
    if boundaries is None:
        boundaries = COL_BOUNDARIES_DEFAULT
    for i, boundary in enumerate(boundaries):
        if x < boundary:
            return i
    return len(boundaries)  # last column


def _layout_blocks(words: list, page_number: int, boundaries: list = None) -> list[dict]:
    """Preserve readable PDF lines and their evidence coordinates."""
    rows = {}
    for word in words:
        top = round(word["top"] / 3) * 3
        rows.setdefault(top, []).append(word)

    result = []
    for index, (top, row_words) in enumerate(sorted(rows.items())):
        ordered = sorted(row_words, key=lambda item: item["x0"])
        text = " ".join(str(item["text"]).strip() for item in ordered if str(item["text"]).strip()).strip()
        if not text:
            continue
        columns = set()
        if page_number == 2 and boundaries:
            for word in ordered:
                if word["x0"] >= 190:
                    columns.add(x_to_weekday_index(word["x0"], boundaries))
        block = {
            "id": f"page{page_number}-block{index + 1}",
            "page": page_number,
            "text": text,
            "x0": round(min(item["x0"] for item in ordered), 1),
            "x1": round(max(item["x1"] for item in ordered), 1),
            "top": round(min(item["top"] for item in ordered), 1),
            "bottom": round(max(item["bottom"] for item in ordered), 1),
        }
        if len(columns) == 1:
            block["weekday"] = COL_INDEX_TO_WEEKDAY[next(iter(columns))]
        result.append(block)
    return result


def parse_ukeplan_pdf(pdf_path: str, member_id: int, year: int = 2026) -> dict:
    result = {
        "week": None, "year": year, "class": None, "teacher": None,
        "theme": None, "homework": {}, "days": {}, "info": "", "raw_text": "",
        "layout_text": "", "source_blocks": [],
        "future_weeks": {}
    }

    with pdfplumber.open(pdf_path) as pdf:
        pages_words = []
        full_text_pages = []
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            pages_words.append(words)
            full_text_pages.append(page.extract_text() or "")

    full_text = "\n".join(full_text_pages)
    result["raw_text"] = full_text

    timetable_words = pages_words[1] if len(pages_words) > 1 else []
    col_boundaries = _compute_col_boundaries(timetable_words)
    source_blocks = []
    for page_index, page_words in enumerate(pages_words, start=1):
        source_blocks.extend(_layout_blocks(page_words, page_index, col_boundaries))
    result["source_blocks"] = source_blocks
    result["layout_text"] = "\n".join(
        f"[{block['id']}] {block.get('weekday', 'general')}: {block['text']}"
        for block in source_blocks
    )

    # --- Metadata ---
    m = re.search(r'uke\s*(\d+)', full_text, re.IGNORECASE)
    if m:
        result["week"] = int(m.group(1))

    m = re.search(r'for\s+(\d[AB])\s+uke', full_text, re.IGNORECASE)
    if m:
        result["class"] = m.group(1)

    m = re.search(r'Tema[:\s]+(.+)', full_text)
    if m:
        result["theme"] = m.group(1).strip()

    for subj, pattern in [
        ("norsk", r'Lekse i norsk\s+(.+)'),
        ("matematikk", r'Lekse i matematikk\s+(.+)'),
        ("engelsk", r'Lekse i engelsk\s+(.+)'),
    ]:
        m = re.search(pattern, full_text)
        if m:
            val = m.group(1).strip()
            if val:
                result["homework"][subj] = val

    # --- Extract dates from header ---
    date_pattern = re.compile(
        r'(\d{1,2})\.\s*(april|mai|juni|august|september|oktober|november|desember|januar|februar|mars)',
        re.IGNORECASE
    )
    week_dates = []
    seen_dates = set()
    for day_str, month_str in date_pattern.findall(full_text):
        d = date(year, MONTHS_NO[month_str.lower()], int(day_str))
        if d not in seen_dates:
            seen_dates.add(d)
            week_dates.append(d)

    # Later dates often appear in the information section. They must not shift
    # the five timetable columns away from the stated ISO week.
    if result["week"]:
        week_dates = [d for d in week_dates if d.isocalendar().week == result["week"]]
        # Some school templates state only the ISO week number. Derive the
        # Monday-Friday range so the child overview still has day rows.
        if not week_dates:
            try:
                week_dates = [
                    date.fromisocalendar(year, result["week"], weekday)
                    for weekday in range(1, 6)
                ]
            except ValueError:
                week_dates = []
    week_dates = sorted(week_dates)[:5]  # max 5 school days

    # Map weekday index to date
    weekday_to_date = {}
    for d in week_dates:
        weekday_to_date[d.weekday()] = d  # 0=Mon, 4=Fri

    # Initialize days
    for d in week_dates:
        iso = d.isoformat()
        weekday_name = ["mandag","tirsdag","onsdag","torsdag","fredag","lørdag","søndag"][d.weekday()]
        result["days"][iso] = {"date": iso, "weekday": weekday_name, "events": [], "bring": []}

    # --- Coordinate-based event extraction from timetable page (page 2) ---
    # Compute column boundaries dynamically from this PDF's day headers
    col_boundaries = _compute_col_boundaries(timetable_words)

    # Group words into rows by top position
    rows = {}
    for w in timetable_words:
        top = round(w['top'] / 4) * 4
        rows.setdefault(top, []).append(w)

    seen_events = set()

    for top, row_words in sorted(rows.items()):
        row_text = " ".join(w['text'] for w in row_words).lower()
        # Skip rows without activity content
        if not any(kw in row_text for kw in ACTIVITY_KEYWORDS):
            continue
        # Skip time/header rows
        if re.match(r'^\d+\.time|^\d{2}:\d{2}', row_text.strip()):
            pass  # still process — activity may be in same row

        # Assign each word to a column
        col_tokens = {i: [] for i in range(5)}
        for w in row_words:
            # Use x0 (start of word) for column assignment
            x = w['x0']
            # Skip left margin (time labels at x < 190)
            if x < 190:
                continue
            col = x_to_weekday_index(x, col_boundaries)
            col_tokens[col].append(w['text'])

        for col_idx, tokens in col_tokens.items():
            if not tokens:
                continue
            # Filter noise tokens before joining
            NOISE = {"x", "og", "til", "og", "og", "fra", "på", "i", "er", "en", "et"}
            clean_tokens = [t for t in tokens if t.lower() not in NOISE and len(t) > 1]
            if not clean_tokens:
                continue
            text = " ".join(clean_tokens).strip()
            if len(text) < 4:
                continue
            # Check it contains an actual activity keyword
            if not any(kw in text.lower() for kw in ACTIVITY_KEYWORDS):
                continue

            # Get the date for this column
            d = weekday_to_date.get(col_idx)
            if not d:
                continue
            iso = d.isoformat()

            # Deduplicate (same event text on consecutive rows)
            key = (iso, text.lower()[:30])
            if key in seen_events:
                continue
            seen_events.add(key)

            result["days"][iso]["events"].append(text)

    # --- Info section ---
    info_match = re.search(
        r'(?:INFORMASJON TIL ELEVER OG FORESATTE[:\s]*|(?:^|\n)Informasjon\s*\n)(.+?)(?:UKENS GLADE NYHETER|\nGod helg!?|$)',
        full_text, re.IGNORECASE | re.DOTALL
    )
    if info_match:
        result["info"] = info_match.group(1).strip()

    # --- Future weeks ---
    search_text = result["info"] or full_text
    future_matches = re.finditer(
        r'Uke\s+(\d+)\s*\n(.+?)(?=Uke\s+\d+|\Z)',
        search_text, re.DOTALL
    )
    for fm in future_matches:
        wk = int(fm.group(1))
        content = fm.group(2).strip()
        if wk != result["week"]:
            result["future_weeks"][wk] = [
                line.strip() for line in content.splitlines() if line.strip()
            ]

    # --- Temporal validation: filter events against stated week ---
    if result["week"]:
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        try:
            from calendar_guard import validate_event
            validated_days = {}
            for iso, day_data in result["days"].items():
                d = date.fromisoformat(iso)
                valid_events = []
                for ev_text in day_data["events"]:
                    vr = validate_event(
                        title=ev_text,
                        event_date=d,
                        stated_week=result["week"],
                        year=result["year"],
                        source="email",
                        allow_past=False,
                    )
                    if vr.ok:
                        valid_events.append(ev_text)
                    else:
                        print(f"  [GUARD REJECTED] {vr.reason}")
                day_data["events"] = valid_events
                validated_days[iso] = day_data
            result["days"] = validated_days
        except ImportError:
            pass  # calendar_guard not available, skip validation

    return result


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: parse_ukeplan.py <pdf_path>")
        sys.exit(1)
    r = parse_ukeplan_pdf(sys.argv[1], member_id=4)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
