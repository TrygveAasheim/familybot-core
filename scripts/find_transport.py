#!/usr/bin/env python3
"""Find Entur StopPlace and direction-specific Quay IDs for FamilyBot config."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


GEOCODER = "https://api.entur.io/geocoder/v1/autocomplete"
JOURNEY_PLANNER = "https://api.entur.io/journey-planner/v3/graphql"


def request_json(request: urllib.request.Request) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("Entur returned an unexpected response")
    return value


def search_stops(text: str, client_name: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"text": text, "lang": "no", "size": 10, "layers": "venue"})
    request = urllib.request.Request(f"{GEOCODER}?{query}", headers={"ET-Client-Name": client_name})
    features = request_json(request).get("features", [])
    results = []
    for feature in features if isinstance(features, list) else []:
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        stop_id = properties.get("id") or properties.get("gid")
        if isinstance(stop_id, str) and "NSR:StopPlace:" in stop_id:
            stop_id = stop_id[stop_id.index("NSR:StopPlace:"):]
        if not isinstance(stop_id, str) or not stop_id.startswith("NSR:StopPlace:"):
            continue
        results.append({
            "name": properties.get("name") or properties.get("label") or "Unknown stop",
            "label": properties.get("label") or "",
            "category": properties.get("category") or [],
            "stop_id": stop_id,
        })
    return results


def departures(stop_id: str, client_name: str) -> list[dict[str, Any]]:
    query = """
    query SetupDepartures($id: String!) {
      stopPlace(id: $id) {
        estimatedCalls(numberOfDepartures: 40, timeRange: 10800) {
          realtime expectedDepartureTime
          destinationDisplay { frontText }
          quay { id publicCode }
          serviceJourney { journeyPattern { line { publicCode transportMode } } }
        }
      }
    }
    """
    body = json.dumps({"query": query, "variables": {"id": stop_id}}).encode("utf-8")
    request = urllib.request.Request(
        JOURNEY_PLANNER,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "ET-Client-Name": client_name},
    )
    payload = request_json(request)
    calls = payload.get("data", {}).get("stopPlace", {}).get("estimatedCalls", [])
    results = []
    for call in calls if isinstance(calls, list) else []:
        line = call.get("serviceJourney", {}).get("journeyPattern", {}).get("line", {})
        quay = call.get("quay") or {}
        results.append({
            "transport_mode": line.get("transportMode") or "",
            "line": line.get("publicCode") or "",
            "destination": call.get("destinationDisplay", {}).get("frontText") or "",
            "direction_quay_id": quay.get("id") or "",
            "platform": quay.get("publicCode") or "",
            "departure": call.get("expectedDepartureTime") or "",
            "realtime": bool(call.get("realtime")),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search Norwegian public-transport stops and inspect direction-specific Entur quays"
    )
    parser.add_argument("search", nargs="?", help="stop/station name, for example 'Oslo S'")
    parser.add_argument("--stop-id", help="inspect departures for an NSR:StopPlace ID")
    parser.add_argument("--client-name", default="familybot-setup-helper", help="Entur ET-Client-Name")
    parser.add_argument("--mode", choices=("metro", "bus", "tram", "rail", "water"))
    parser.add_argument("--line", help="optional public line number/name filter")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    if not args.search and not args.stop_id:
        parser.error("provide a station search or --stop-id")

    if args.stop_id:
        rows = departures(args.stop_id, args.client_name)
        if args.mode:
            rows = [row for row in rows if row["transport_mode"] == args.mode]
        if args.line:
            rows = [row for row in rows if str(row["line"]) == args.line]
        label = "departures"
    else:
        rows = search_stops(args.search, args.client_name)
        label = "stops"

    if args.json:
        print(json.dumps({label: rows}, ensure_ascii=False, indent=2))
        return
    if not rows:
        raise SystemExit("No matching Entur data found. Try a broader station name or remove filters.")
    for index, row in enumerate(rows, 1):
        if label == "stops":
            print(f"{index}. {row['name']} — {row['stop_id']} — {row['label']}")
        else:
            realtime = "realtime" if row["realtime"] else "scheduled"
            print(
                f"{index}. {row['transport_mode']} line {row['line']} → {row['destination']} | "
                f"quay {row['direction_quay_id']} platform {row['platform']} | {realtime} {row['departure']}"
            )


if __name__ == "__main__":
    main()
