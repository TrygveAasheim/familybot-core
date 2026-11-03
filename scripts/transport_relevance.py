#!/usr/bin/env python3
"""Parse Entur SIRI notices and keep only incidents relevant to a route corridor."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Iterable

SKIP_KEYWORDS = (
    "forsinkels", "delay", "noe forsinket", "minor delay",
    "ikke egnet for rullestol", "not suitable for wheelchair",
    "stengt holdeplass", "closed stop",
)
STATION_SCOPED_KEYWORDS = (
    "heis", "elevator", "rulletrapp", "escalator", "plattform", "platform",
)


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(value or ""))).casefold()
    return " ".join(re.sub(r"[^\wæøå]+", " ", text).split())


def _text_values(fragment: str, element_names: Iterable[str]) -> set[str]:
    names = "|".join(re.escape(name) for name in element_names)
    values = re.findall(
        rf"<(?:{names})\b[^>]*>\s*(?:<Value\b[^>]*>\s*)?([^<]+)",
        fragment,
        re.IGNORECASE,
    )
    return {html.unescape(value).strip() for value in values if value.strip()}


def parse_siri_disruptions(data: str, valid_lines: set[str]) -> list[dict]:
    """Return normalized disruption records from an Entur SIRI-SX document."""
    disruptions = []
    situations = re.findall(r"<PtSituationElement\b[^>]*>(.*?)</PtSituationElement>", data, re.DOTALL)
    for situation in situations:
        lines = set(re.findall(r"<LineRef\b[^>]*>\s*RUT:Line:(\d+)\s*</LineRef>", situation))
        summaries = re.findall(
            r"<Summary\b[^>]*lang=[\"']NO[\"'][^>]*>\s*(?:<Value\b[^>]*>\s*)?([^<]+)",
            situation,
            re.IGNORECASE,
        )
        if not summaries:
            summaries = re.findall(
                r"<Summary\b[^>]*>\s*(?:<Value\b[^>]*>\s*)?([^<]+)", situation, re.IGNORECASE
            )
            summaries = summaries[::2] if len(summaries) > 1 else summaries
        summary = html.unescape(summaries[0]).strip() if summaries else ""
        if not summary or any(keyword in summary.casefold() for keyword in SKIP_KEYWORDS):
            continue
        transit_lines = lines & valid_lines
        if not transit_lines:
            continue
        stop_names = _text_values(situation, ("StopPointName", "StopPlaceName"))
        stop_refs = _text_values(situation, ("StopPointRef", "StopPlaceRef"))
        disruptions.append({
            "lines": sorted(transit_lines),
            "summary": summary,
            "stop_names": sorted(stop_names),
            "stop_refs": sorted(stop_refs),
            "key": f"{','.join(sorted(transit_lines))}:{summary[:50]}",
        })
    return disruptions


def notice_relevant(disruption: dict, corridor_stops: Iterable[str], corridor_stop_ids: Iterable[str] = ()) -> bool:
    """Keep line-wide notices, but constrain station-scoped notices to the configured corridor."""
    corridor_names = {_normalized(value) for value in corridor_stops if _normalized(value)}
    corridor_refs = {str(value).strip() for value in corridor_stop_ids if str(value).strip()}
    affected_names = {_normalized(value) for value in disruption.get("stop_names", []) if _normalized(value)}
    affected_refs = {str(value).strip() for value in disruption.get("stop_refs", []) if str(value).strip()}

    if not corridor_names and not corridor_refs:
        return True
    if corridor_refs & affected_refs:
        return True

    def mentions_corridor(text: str) -> bool:
        return any(re.search(rf"(?:^|\s){re.escape(stop)}(?:\s|$)", text) for stop in corridor_names)

    if affected_names:
        return any(mentions_corridor(name) for name in affected_names)
    if corridor_refs and affected_refs:
        return False

    summary = _normalized(disruption.get("summary"))
    if corridor_names and mentions_corridor(summary):
        return True
    if corridor_names and any(keyword in summary for keyword in STATION_SCOPED_KEYWORDS):
        return False
    return True


def classify_for_corridor(
    disruptions: Iterable[dict],
    configured_line: str,
    corridor_stops: Iterable[str],
    corridor_stop_ids: Iterable[str] = (),
    *,
    all_lines: set[str] | None = None,
    system_threshold: int = 4,
) -> dict[str, list[dict]]:
    """Split relevant notices into configured-route and genuinely system-wide groups."""
    valid_lines = all_lines or {"1", "2", "3", "4", "5", "6"}
    route = []
    system = []
    for disruption in disruptions:
        if not notice_relevant(disruption, corridor_stops, corridor_stop_ids):
            continue
        lines = set(disruption.get("lines", [])) & valid_lines
        if len(lines) >= system_threshold:
            system.append(disruption)
        elif configured_line in lines:
            route.append(disruption)
    return {"route": route, "system": system}
