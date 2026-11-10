# FamilyBot Core

FamilyBot is a local-first family planner for Norwegian households. It combines
a calm iPad dashboard with deterministic ingestion of school information,
Norwegian calendars, MET weather, Entur transport and optional Spond activity
data. Chores, rewards, Kanban and grocery integrations live in the sibling
`familybot-portal` repository.

The minimum product does **not** require OpenClaw, Telegram, email, Spond or an
AI account. Start with the dashboard, then enable connected or conversational
capabilities deliberately.

## Start here

The canonical guide for both repositories is
[`GETTING_STARTED.md`](GETTING_STARTED.md). A new Mac installation is:

```bash
mkdir -p "$HOME/FamilyBot" && cd "$HOME/FamilyBot"
git clone --branch main https://github.com/TrygveAasheim/familybot-core.git
git clone --branch main https://github.com/TrygveAasheim/familybot-portal.git
cd familybot-core
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal
```

Install the prerequisites in the canonical guide first. Use `main` in both
repositories, never a mix of release tracks. Record both commit IDs with your
backup. This is a published installation candidate with automated lifecycle
coverage, not certification of a physical Mac/iPad or any provider account.
See [readiness and remaining checks](docs/INSTALLATION_READINESS.md).

The guided installer checks the supported macOS toolchain, creates private
configuration and a parent PIN, initializes an empty SQLite database, applies
versioned Core and Portal migrations, builds the Portal and verifies its local
health. No starter database and no OpenClaw workspace are required.
Readiness allows configured weather/transport adapters time to return their
unavailable states; their outage must not be confused with a failed local API.

To explore with entirely fictional data first, add `--demo`. The default private
workspace for a new installation is `$HOME/.familybot`.

## Capability profiles

| Profile | Useful by itself | Optional dependencies |
| --- | --- | --- |
| **Dashboard** | Family members, child pages, chores, rewards, Kanban and local dashboard; MET and Entur when configured | Core + Portal only |
| **Connected organizer** | Dashboard plus school email/PDF ingestion, deterministic Ukeplan parsing, Spond and scheduled processing | Himalaya and/or unofficial Spond client credentials |
| **AI family agent** | Connected profile plus model-assisted Ukeplan interpretation, briefings and Telegram | OpenClaw, a supported model account and Telegram bot |

Oda and HelloFresh are separate Portal capabilities. Neither is required by a
profile.

## Repository boundary

Keep both repositories as sibling checkouts:

```text
familybot-core/       configuration, migrations, ingestion, schedules, health
familybot-portal/     curated local API, dashboard, chores, rewards, groceries
```

Core owns normalized source facts and schema version `core:1`. Portal owns its
interaction tables and schema version `portal:2`. Both record migrations in the
same private database and refuse incompatible versions before serving traffic.
Portal depends on Core's configuration and database contract, but Core remains
usable without the Portal UI for deterministic processing.

The detailed ownership map is in
[`docs/REPOSITORY_GUIDE.md`](docs/REPOSITORY_GUIDE.md), and architecture is in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Privacy and network boundary

The dashboard is plain HTTP on a trusted household LAN by default. SQLite,
configuration, credentials, logs and backups stay on the Mac. Do not port-forward
ports `3000` or `8788` and do not use provider login forms on guest or hostile
Wi-Fi. Use an authenticated VPN—and TLS when the network itself is not
trusted—for remote access.

Data leaves the home only through capabilities the household enables: MET,
Entur, school mail, Spond, Telegram/model processing, Oda or HelloFresh. The
exact data-flow and residual risks are documented in
[`SECURITY.md`](SECURITY.md) and the Portal's `docs/DATA_BOUNDARY.md`.

## Supported operations

- Versioned, transactional empty-database initialization and migrations.
- Automatic verified backup before changing an existing schema.
- Explicit backup, status and restore commands in `scripts/manage_database.py`.
- Profile-aware `launchd` schedules and health checks: disabled integrations do
  not create false failures.
- Briefing quality alerts count actual fallback generations, not repeated polls;
  [schedule diagnostics](docs/SCHEDULES.md) detect and safely retire legacy cron duplicates.
- Deterministic fallbacks when inference or an external integration is down.
- [OpenClaw setup checks](docs/OPENCLAW_SETUP_AUDIT.md) detect missing local Codex
  executables; briefing fallbacks point to full plans instead of dumping PDFs.
- Optional [weekly stack/security inventory](docs/STACK_SECURITY.md), with
  explicit runtime paths and no unattended upgrades or Telegram noise.
- Fictional demo data in `config/family.demo.json`.
- Linux unit/security CI plus a macOS clean-install lifecycle check.

See [`CONFIGURATION.md`](CONFIGURATION.md) for household fields and
[`REDEPLOY.md`](REDEPLOY.md) for upgrade, backup, restore and rollback.

Existing households: do not rerun the fresh-install command. Use the explicit
upgrade procedure with the actual workspace/runtime and all database users
stopped. The candidate preserves archived chores, disabled rewards, omitted
member metadata and stored school dates; it creates a full pre-upgrade backup.
Physical household rollout checks remain outstanding. Merging source is not
deployment or proof of a live upgrade.

## Integration support level

- MET Locationforecast and Entur Journey Planner are official public APIs.
- IMAP is accessed through Himalaya; mailbox support depends on the mail
  provider.
- Spond uses an unofficial community client and may break when Spond changes.
- Oda uses Oda's hosted MCP/OAuth surface; availability and contract stability
  remain provider-controlled.
- HelloFresh account support is experimental and uses an unsupported,
  reverse-engineered Norway web contract behind disabled feature flags.
- OpenClaw is optional orchestration for the AI/Telegram profile, not the
  database, dashboard or scheduler.

## Engineering entry points

- [Reliability invariants](specs/RELIABILITY.md)
- [Change protocol](docs/CHANGE_PROTOCOL.md)
- [New-session verification](docs/NEW_SESSION_VERIFICATION.md)
- [Smart Home plan—not a shipped feature](specs/SMART_HOME.md)
- [Credential boundaries](CREDENTIALS.md)
- [Branch and release policy](docs/BRANCHES.md)
- [Installation readiness and residual risks](docs/INSTALLATION_READINESS.md)

Git backs up source only. It never replaces an encrypted backup of household
state.
