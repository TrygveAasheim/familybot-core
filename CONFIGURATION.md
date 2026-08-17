# Configuration

FamilyBot has exactly one configuration template:
[`config/family.example.json`](config/family.example.json) in this repository.
The core and portal read one populated, machine-local copy. The portal repository
does not carry a second template.

## Create the local file

From the `familybot-core` checkout:

```bash
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
python3 scripts/validate_config.py
```

The validator prints paths and diagnoses, never family values. It rejects
unreplaced placeholders, unsafe permissions, duplicate IDs, bad coordinates,
broken references and malformed portal origins.

## Field reference

| Path | Required | Purpose |
| --- | --- | --- |
| `schema_version` | yes | Configuration contract; currently `1` |
| `family.display_name` | yes | Household label shown in family-facing text |
| `family.locale` | yes | Locale, normally `nb-NO` |
| `family.timezone` | yes | IANA time zone, normally `Europe/Oslo` |
| `portal.hostname` | yes | Bonjour/mDNS browser name, normally `familie.local` |
| `portal.web_port`, `api_port` | yes | Local web and curated API ports |
| `portal.bonjour_name` | yes | Service name advertised by DNS-SD |
| `portal.allowed_origins[]` | yes | Exact browser origins allowed to call the API |
| `members[].member_id` | yes | Stable positive integer matching `family_members.id` |
| `members[].role` | yes | `parent` or `child` |
| `members[].name`, `slug` | yes | Local display name and durable lowercase key |
| `members[].telegram_target` | when Telegram is used | Recipient identifier; parents only |
| `members[].grade` | recommended for children | School-email and `ukeplan` routing context |
| `members[].avatar` | optional | Child dashboard avatar |
| `members[].default_reward` | optional | Initial portal reward definition |
| `integrations.email` | when email job is enabled | Himalaya account label and known forwarding addresses |
| `integrations.spond.groups[]` | when Spond job is enabled | Group ID, label and optional owning `member_id` |
| `integrations.transport` | dashboard | Entur stop, quay, line, direction and client label |
| `integrations.weather` | dashboard/briefing | MET user agent and coordinates |

A Spond group may omit or set `member_id` to `null` when it belongs to the
whole household. Never renumber members after the database contains events,
plans, chores or rewards.

## Optional integrations

Remove an unused optional integration block and do not install its LaunchAgent.
The configuration file does not enable or disable schedules by itself. The
home weather and transport blocks are required by the current dashboard.

The three cabin fields are all-or-none:
`cabin_label`, `cabin_lat`, and `cabin_lon`.

`portal.allowed_origins` is an allowlist, not a wildcard. Add an IP-based origin
only if an iPad must use it, for example `http://192.168.1.50:3000`. Do not add
arbitrary `.local` hosts or entire private ranges.

## Overrides

- `FAMILYBOT_FAMILY_CONFIG`: alternate populated JSON path.
- `FAMILYBOT_WORKSPACE`: alternate workspace for both repositories.
- `OPENCLAW_WORKSPACE`: legacy core workspace override.
- `FAMILYBOT_DB_PATH`: alternate SQLite database.
- `FAMILYBOT_PORTAL_RUNTIME`: alternate deployed portal runtime.

Set overrides explicitly in LaunchAgent plists; launchd does not inherit shell
startup files.

## What does not belong here

This file contains private household metadata but no passwords, bearer tokens,
session cookies, API keys or parent PIN. Those belong in separate owner-only
stores described in [CREDENTIALS.md](CREDENTIALS.md). Keep the populated file
at mode `0600` and outside every Git checkout.
