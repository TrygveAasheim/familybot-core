# Repository guide and system boundaries

This is the canonical orientation guide for a person or agent arriving without
conversation history. It describes what FamilyBot is, where each responsibility
lives and which parts require the highest change discipline.

## Product in one paragraph

FamilyBot reduces the family's planning burden. Deterministic jobs collect
school email, `ukeplan` documents, Spond events, calendar facts, weather and
transport data. SQLite holds normalized durable state. OpenClaw supplies the
conversational and Telegram layer. The sibling `familybot-portal` repository is
the iPad-first family interface used directly by parents and children.

## The three repositories and runtimes

| Component | Responsibility | Must not become |
| --- | --- | --- |
| `familybot-core` | Ingestion, parsing, normalized facts, briefings, durable delivery, health and canonical configuration | A web UI or vendor-appliance collection |
| `familybot-portal` | Curated local API, family/child/parent UI, chores and rewards | An OpenClaw admin console or raw database browser |
| OpenClaw workspace | Private database, config, attachments, credentials, operational memory and deployed scripts | Source control |

Home Assistant is the planned integration broker for Smart Home features. It is
not yet a core dependency and must remain outside the ingestion/delivery
durability boundary.

## Sources of truth

Use this order when facts disagree:

1. Normalized SQLite rows and their owning ledger/outbox state.
2. The owner-only canonical family configuration.
3. Reviewed source and migrations in Git.
4. Generated operational snapshots such as `STATUS.md`.
5. Inference output and conversational memory.

Within an OpenClaw conversation, `STATUS.md`, `MEMORY.md` and `SKILLS.md` help a
session orient itself, but they do not override SQLite, configuration or source
contracts. An LLM response is never proof that ingestion or delivery succeeded.

## Reliability core

The following capabilities constitute the core and should be changed with
utmost respect for correctness, compatibility and recovery:

- email listing, routing, attachment handling and retry state;
- `ukeplan` PDF parsing and member/week attribution; PDF content is authoritative
  whenever a plan email contains a PDF, while email transport text is excluded
  from stored plan content;
- normalized calendar, activity, Spond and week-plan facts;
- deterministic daily/weekly data collection and fallback rendering;
- recipient-specific delivery outbox, leases, retries and expiry;
- atomic state writes, SQLite connection settings and schema ownership;
- scheduled-task ownership, health checks and status reporting;
- the canonical local configuration contract and validator.

The core promise is not that every upstream source is always available. The
promise is that failures are explicit, retryable where appropriate, do not
erase good facts and do not silently suppress the rest of the briefing.

## Bounded adapters

Spond, Himalaya, MET and Entur sit at the edge. Treat their responses as
untrusted and versionable. Each adapter must apply timeouts, bounded parsing,
validation and honest freshness/error reporting. Upstream changes should break
one adapter, not the database, briefing pipeline or dashboard.

## Add-ons

Add-ons improve family life without defining whether FamilyBot has correctly
processed and delivered its core information:

- Familieportalen presentation and touch interactions;
- chores, completions, approvals and rewards;
- Smart Home devices, cameras and climate control;
- meal/menu providers and local event discovery;
- optional conversational conveniences.

An add-on may read curated facts and own its own tables. It may not mark an
email processed, mutate delivery state, expose raw email/Spond payloads or make
core jobs depend on its availability.

## Code map

| Area | Owning files |
| --- | --- |
| Shared durability primitives | `scripts/reliability.py` |
| Email ingestion and ledger transitions | `scripts/process_emails.py` |
| Sender/member classification | `scripts/email_routing.py` |
| Weekly-plan parsing | `scripts/parse_ukeplan.py` |
| Calendar validation and school dates | `scripts/calendar_guard.py`, `scripts/calendar_seed.py` |
| Spond adapter | `scripts/spond_sync.py` |
| Fact aggregation and external weather/transport | `scripts/briefing_data.py` |
| Rendering, queuing and preview | `scripts/briefing.py` |
| Delivery worker | `scripts/flush_outbox.py` |
| Health/status | `scripts/healthcheck.py`, `scripts/update_status.py` |
| Canonical household contract | `config/family.example.json`, `scripts/family_config.py`, `scripts/validate_config.py` |
| Schedule wrapper | `scripts/cron_runner.sh`, `ops/launchd/` |

## Private runtime boundary

Reviewed source lives in Git. Private durable state normally lives under:

```text
$HOME/.openclaw/workspace/
  config/family.local.json
  db/family.db
  attachments/
  backups/
  logs/
  secrets.env
```

Do not solve a source problem by editing only the deployed workspace copy. Fix
and test the repository, then deploy deliberately. Do not solve a runtime-state
problem by committing the database or generated status files.

## Where to start for common work

| Intended change | Read first | Primary verification |
| --- | --- | --- |
| Email or `ukeplan` behaviour | `specs/RELIABILITY.md`, `docs/CHANGE_PROTOCOL.md` | Unit fixtures, copied DB, retry/failure path |
| Family member, school or transport config | `CONFIGURATION.md` | `scripts/validate_config.py` |
| Telegram briefing/delivery | `specs/RELIABILITY.md` | deterministic preview, outbox tests, deliberate smoke send |
| Portal/UI/API | sibling portal `AGENTS.md`, `docs/DATA_BOUNDARY.md` | lint, unit/build and acceptance suite |
| Smart Home/appliance | `specs/SMART_HOME.md` | provider contract tests; no core regression |
| Deployment or recovery | `REDEPLOY.md`, `docs/BRANCHES.md` | backup, preflight, service health and rollback evidence |

## Current product status

The deterministic family-information pipeline and the LAN portal exist. Smart
Home is a documented add-on plan, not a deployed integration. Do not describe a
planned appliance as connected until live state and a safe command have been
verified through the chosen provider.
