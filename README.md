# FamilyBot

FamilyBot is loosely based on OpenClaw's local-first household-agent ideas, but
much of the system is custom to make planning practical for Norwegian
households: school `ukeplan` processing, Spond activities, Norwegian calendars,
MET weather, Entur transport and Norwegian family routines. It is a local-first
family information service for households that want their planning data kept
close to home.
An always-on Mac mini processes school email and `ukeplan` PDFs, Spond,
Norwegian calendar data, MET weather and Entur transport; OpenClaw provides the
conversational/Telegram layer; Familieportalen provides the iPad-first touch UI.

> **Built for local family life:** the reliability layer and dashboard model are
> reusable, while the included school, calendar, transport and activity adapters
> can be configured for the services used by each household.

## Network and security boundary

FamilyBot is designed to run as a LAN-only service on an always-on household
Mac. Its local configuration, database, ingestion jobs and dashboard data stay
on the home network. Telegram is the intentional external integration, using
the conversational layer supplied by OpenClaw. The security controls therefore
provide defense in depth for a self-hosted home appliance: owner-only files,
credential separation, input validation, idempotent delivery, curated data
boundaries and safe local deployment. This is not an internet-facing
multi-tenant service, and it should not be exposed directly to the public
internet without an explicit security review and additional perimeter
controls.

## What is in this repository

- deterministic email/PDF routing and weekly-plan extraction, with optional
  validated LLM enrichment for readable day/category structure;
- Spond synchronization through an unofficial community client;
- Norwegian calendar, weather and transport inputs;
- SQLite reliability primitives, ingestion ledger and delivery outbox;
- launchd-compatible scheduled jobs, health and status reporting;
- source-controlled LaunchAgent templates with schedule validation and an
  explicit installer;
- the **one canonical family configuration template**.

The sibling `familybot-portal` repository contains the responsive LAN dashboard.
Inference may improve family-facing wording, but it is not part of the
durability boundary.

## Dependencies and repository layout

`familybot-core` is the reliability foundation; `familybot-portal` is its
separate LAN-facing add-on. Keep the checkouts as siblings:

```text
familybot-core/
familybot-portal/
```

The operational dependency map is:

- Core owns the canonical `family.local.json` template, normalized SQLite facts,
  ingestion/delivery jobs, schedules and health reporting;
- Portal reads the same owner-only local configuration and SQLite database,
  validates against Core's configuration contract, and owns its curated API,
  UI, chores and rewards tables;
- OpenClaw supplies the conversational/Telegram layer and private workspace
  convention; it is optional for the deterministic Core pipeline;
- macOS `launchd`, Python 3, SQLite and Node.js/npm (for Portal) are required by
  the local appliance deployment.

Clone and configure Core first, then install and deploy Portal. Keep both
repositories on compatible `dev` commits and run both verification suites before
promoting either one to `main`; this is an operational compatibility contract,
not a Python or npm package dependency.

## Telegram child-chore interview

The conversational layer should use the separate `chore-preview` and
`chore-create` commands in `scripts/kanban.py` when a family wants to add a
real child chore. Preview gathers and normalizes the child, points, repeat
weekdays and approval setting; creation requires explicit confirmation and an
idempotency key. The command delegates storage to the sibling portal, which
owns the child-chore metadata and validation. Generic `kanban.py add` remains
for parent Kanban tasks. The complete handoff contract is documented in the
portal repository at `docs/TELEGRAM_CHILD_CHORES.md`.

## Start here

For a coding agent or a session without prior context, begin with
[`AGENTS.md`](AGENTS.md), then follow this map:

1. [Repository guide and core/add-on boundaries](docs/REPOSITORY_GUIDE.md)
2. [New-user walkthrough](GETTING_STARTED.md)
3. [Architecture and Mac mini/iPad topology](ARCHITECTURE.md)
4. [Reliability invariants](specs/RELIABILITY.md)
5. [Change protocol](docs/CHANGE_PROTOCOL.md)
6. [Canonical configuration](CONFIGURATION.md)
7. [Credential/token checklist](CREDENTIALS.md)
8. [Security and OWASP posture](SECURITY.md)
9. [Redeploy and disaster recovery](REDEPLOY.md)

Smart Home is a documented add-on plan, not a current core capability. See
[`specs/SMART_HOME.md`](specs/SMART_HOME.md). Documentation handoff quality is
tested with [`docs/NEW_SESSION_VERIFICATION.md`](docs/NEW_SESSION_VERIFICATION.md).
The Ukeplan source/interpretation contract and its incident safeguards are in
[`docs/UKEPLAN_INTERPRETATION.md`](docs/UKEPLAN_INTERPRETATION.md).

## Canonical local configuration

Only [`config/family.example.json`](config/family.example.json) is a template.
Copy it outside Git and validate it:

```bash
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
python3 scripts/validate_config.py
```

The populated file holds private metadata and routing IDs, never passwords or
tokens. Both core and portal read the same file.

## Verify source

```bash
python3 scripts/validate_docs.py
python3 scripts/validate_config.py \
  --config config/family.example.json --allow-placeholders --skip-permissions
python3 scripts/validate_launchd.py
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh
```

Runtime SQLite, email attachments, credentials, OpenClaw memory, logs and
backups are deliberately excluded from Git. Git is a source backup, not a
household-state backup.

## Development and release

`dev` is the working and deployment branch. `main` is the public release and
fork baseline; GitHub branch protection is intentionally not enabled because
forks are the expected customization path. See [docs/BRANCHES.md](docs/BRANCHES.md)
and [specs/RELIABILITY.md](specs/RELIABILITY.md).
