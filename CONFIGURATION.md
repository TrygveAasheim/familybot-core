# Configuration

FamilyBot has exactly one configuration template:
[`config/family.example.json`](config/family.example.json) in this repository.
The core and portal read one populated, machine-local copy. The portal repository
does not carry a second template.

## Create the local file

The guided installer creates the private file automatically. To create one
manually from the `familybot-core` checkout:

```bash
install -d -m 700 "$HOME/.familybot/config"
install -m 600 config/family.example.json \
  "$HOME/.familybot/config/family.local.json"
${EDITOR:-nano} "$HOME/.familybot/config/family.local.json"
FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json" \
  python3 scripts/validate_config.py
```

The validator prints paths and diagnoses, never family values. It rejects
unreplaced placeholders, unsafe permissions, duplicate IDs, bad coordinates,
broken references and malformed portal origins.

## Field reference

| Path | Required | Purpose |
| --- | --- | --- |
| `schema_version` | yes | Configuration contract; currently `1` |
| `profile` | yes for new installs | `dashboard`, `connected`, or `agent`; missing is legacy `agent` compatibility |
| `family.display_name` | yes | Household label shown in family-facing text |
| `family.locale` | yes | Locale, normally `nb-NO` |
| `family.timezone` | yes | IANA time zone, normally `Europe/Oslo` |
| `portal.hostname` | yes | Bonjour/mDNS browser name, normally `familie.local` |
| `portal.web_port`, `api_port` | yes | Local web and curated API ports |
| `portal.bonjour_name` | yes | Service name advertised by DNS-SD |
| `portal.allowed_origins[]` | yes | Exact browser origins allowed to call the API |
| `portal.features.hellofresh` | optional | Boolean, off by default; exposes only Portal's experimental public Norwegian HelloFresh menu |
| `portal.features.hellofresh_account` | optional | Boolean, off by default; enables Portal's transient email/password, persistent token-only, read-only HelloFresh account test when `hellofresh` is also enabled |
| `members[].member_id` | yes | Stable positive integer matching `family_members.id` |
| `members[].role` | yes | `parent` or `child` |
| `members[].name`, `slug` | yes | Local display name and durable lowercase key |
| `members[].telegram_target` | when Telegram is used | Recipient identifier; parents only |
| `members[].grade` | recommended for children | School-email and `ukeplan` routing context |
| `members[].school`, `teacher` | optional | Per-child school context; different children may use different schools |
| `members[].avatar` | optional | Child dashboard avatar |
| `members[].default_reward` | optional | Initial portal reward definition |
| `integrations.email` | when email job is enabled | Himalaya account label and known forwarding addresses |
| `integrations.spond.groups[]` | when Spond job is enabled | Group ID, label and optional owning `member_id` |
| `school.municipality`, `calendar_events[]` | optional | Household municipality and its authoritative school dates |
| `notifications.*` | agent only | Enable/disable briefings and configure local delivery times |
| `integrations.*.enabled` | optional | Explicitly disable one configured adapter without deleting its settings |
| `integrations.transport` | optional | Entur stop, direction-specific quay, mode, line and labels |
| `integrations.weather` | optional | MET user agent, required home coordinates and optional secondary location |

A Spond group may omit or set `member_id` to `null` when it belongs to the
whole household. Never renumber members after the database contains events,
plans, chores or rewards.

`member_id` and `role` are the durable household identity. Re-running the
installer or database initializer may update a member's display name, grade,
school and teacher; it creates a verified `core-profile-*` backup first and
keeps name-based Kanban assignments in sync. Changing a member's role is
rejected because historical rows already refer to that identity. Removing a
member from configuration does not delete or deactivate their database record:
preserving that history is deliberate. Archive their active work first and
keep the existing ID reserved; automated member retirement is not yet a
supported operation.

## Profiles and optional integrations

An absent integration block is disabled. A present block can also set
`"enabled": false`; disabled blocks require no other fields and are omitted from
deployment, health and status checks. The dashboard remains usable without
weather or transport and shows an honest unavailable state instead.

Profile selection controls the background footprint:

- `dashboard`: no Core LaunchAgents and no external account required;
- `connected`: health/status plus only configured email, Spond and transport
  jobs;
- `agent`: connected jobs plus selected briefings, delivery and model-assisted
  Ukeplan interpretation.

Changing JSON alone does not load or unload a macOS service. Validate, then run
`bash scripts/deploy_core.sh --reload` for a deliberate profile change.

The three cabin fields are all-or-none:
`cabin_label`, `cabin_lat`, and `cabin_lon`.

School dates are configuration-owned because Norwegian municipalities and
individual schools differ. Add `first_day`, `last_day`, `break`,
`planning_day` or `school_event` entries with ISO dates. `calendar_seed.py`
replaces the local school-calendar rows from this list and derives national
public holidays for the current surrounding years; it does not ship or retain
an Oslo calendar when another household configuration is applied.

Notification times use `HH:MM` in `family.timezone` and therefore follow the
IANA daylight-saving rules installed with Python. Available fields are
`weekday_briefing`, `weekend_briefing`, `weekly_summary`, `weekday_time`,
`weekend_time`, `weekly_time` and `weekly_weekday`.

## Configure Ruter or other Norwegian public transport

The dashboard does not call a household-specific Ruter API. Ruter departures
are published through Entur's national Journey Planner, so the same setup also
works for supported bus, tram, train and ferry services elsewhere in Norway.
No Ruter or Entur token is required, but Entur requires a descriptive
`ET-Client-Name`.

Choose the stop the family actually departs **from**, then choose the exact
quay/platform for the wanted direction. A station's opposite platforms have
different `NSR:Quay` IDs; selecting only the station is not enough to distinguish
"toward the centre" from the opposite direction.

The included helper performs both lookups:

```bash
# 1. Find candidate stations/stops and their NSR:StopPlace IDs.
python3 scripts/find_transport.py "STATION OR STOP NAME" \
  --client-name "surname-familybot"

# 2. Inspect upcoming destinations, lines and direction-specific quays.
python3 scripts/find_transport.py \
  --stop-id "NSR:StopPlace:NUMBER" \
  --client-name "surname-familybot"

# Optional filtering for a busy multimodal stop.
python3 scripts/find_transport.py \
  --stop-id "NSR:StopPlace:NUMBER" \
  --mode metro --line 2 \
  --client-name "surname-familybot"
```

Match the destination text to the direction your family needs, then copy these
fields into the local configuration:

| Field | What to enter |
| --- | --- |
| `transport_mode` | `metro`, `bus`, `tram`, `rail`, or `water` |
| `stop_name` | Family-facing stop/station label |
| `stop_id` | Selected `NSR:StopPlace:…` from step 1 |
| `direction_quay_id` | `NSR:Quay:…` for the wanted platform/direction from step 2 |
| `line` | Public line number/name shown by Entur |
| `route_description` | Plain description, for example “line 2 from the local station toward the city” |
| `direction_label` | Dashboard label, for example “Next toward the city centre” |
| `alert_stops` | Ordered station names in the part of the route the household actually uses |
| `alert_stop_ids` | Optional Entur stop/quay IDs for stricter matching when they are known |
| `client_name` | Identifiable Entur client name, normally `surname-familybot` |

`centre_quay_id` remains accepted as a compatibility alias for older local
files; new configurations should use `direction_quay_id`. The current dashboard
card follows one configured mode/line/direction. Multiple independent commuter
routes require an additional adapter/card rather than comma-separated IDs.

The disruption monitor applies the line filter first and then the configured
station corridor. Station-scoped notices outside `alert_stops` are ignored;
line-wide operational notices without a station scope are retained. This same
filter is used for Telegram alerts and morning briefings. List every station
between the household's start and destination, including both endpoints.

After editing, run `python3 scripts/validate_config.py`, deploy, and confirm that
the displayed destinations and platform are correct before relying on the
countdown.

`portal.allowed_origins` is an allowlist, not a wildcard. Add an IP-based origin
only if an iPad must use it, for example `http://192.168.1.50:3000`. Do not add
arbitrary `.local` hosts or entire private ranges.

## Overrides

- `FAMILYBOT_FAMILY_CONFIG`: alternate populated JSON path.
- `FAMILYBOT_WORKSPACE`: private workspace for both repositories. New installs
  default to `$HOME/.familybot`; existing OpenClaw-based installs may keep their
  prior path.
- `OPENCLAW_WORKSPACE`: legacy core workspace override.
- `FAMILYBOT_DB_PATH`: alternate SQLite database.
- `FAMILYBOT_PORTAL_RUNTIME`: alternate deployed portal runtime.
- `FAMILYBOT_OPENCLAW_MODEL`: expected default model for the Telegram agent and
  scheduled agent jobs; default `openai/gpt-5.6-sol`.
- `FAMILYBOT_UKEPLAN_MODEL`, `FAMILYBOT_BRIEFING_MODEL`: explicit OpenAI models
  for interpretation and briefing generation; default `openai/gpt-5.6-sol`.
  The model must be allowed in OpenClaw and available to its authenticated
  account. Both jobs refuse a non-OpenAI model. When using the Codex runtime,
  keep `agentRuntime.id=codex` on the model entry in OpenClaw's allowlist.
  Verify with a small no-delivery request after account/model changes; a catalog
  entry alone does not establish live access.

Audit the global default and every enabled or disabled OpenClaw cron job before
deployment. Apply repairs deliberately, then run an actual no-delivery agent
turn to prove account access:

```bash
python3 scripts/configure_openclaw_model.py --check
python3 scripts/configure_openclaw_model.py --apply --restart
openclaw agent --agent main --message "Reply exactly: MODEL_OK" --json
```

The repair changes the global default and clears only known-retired cron model
pins so those jobs inherit the supported default. It preserves other explicit
per-job overrides. Override the expected model with
`FAMILYBOT_OPENCLAW_MODEL`; extend the comma-separated retired set with
`FAMILYBOT_RETIRED_OPENCLAW_MODELS`. Model availability changes over time, so
confirm the choice in the [OpenAI model catalog](https://developers.openai.com/api/docs/models)
and with the authenticated smoke test.

Set overrides explicitly in LaunchAgent plists; launchd does not inherit shell
startup files.

## What does not belong here

This file contains private household metadata but no passwords, bearer tokens,
session cookies, API keys or parent PIN. Those belong in separate owner-only
stores described in [CREDENTIALS.md](CREDENTIALS.md). Keep the populated file
at mode `0600` and outside every Git checkout.
