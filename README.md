# FamilyBot Core 🇳🇴

> **Norway-first deployment.** This repository contains the deterministic,
> self-hosted core for a Norwegian family setup built around OpenClaw. Several
> integrations and parsers are intentionally Norwegian rather than generic.

FamilyBot Core handles email ingestion and routing, Norwegian weekly-plan
parsing, Spond synchronization, weather and transport collection, durable
Telegram delivery, health checks and runtime status. Inference may improve the
wording, but it is not part of the durability boundary.

## Norwegian integration profile

| Area | Current assumption |
| --- | --- |
| School communication | Norwegian `ukeplan`, grade/class expressions and Norwegian-language PDFs and email |
| School calendar | Norwegian public holidays and Oslo school-year data |
| Activities | Spond group synchronization |
| Public transport | Entur Journey Planner and configured Norwegian stop/quay IDs |
| Weather | MET Norway Locationforecast |
| Delivery | OpenClaw as the Telegram gateway, with Norwegian family-facing output |
| Hosting | Always-on macOS host with launchd and local SQLite |

The retry queues, email ledger, health checks, atomic state handling and
deterministic fallbacks are reusable elsewhere. A non-Norwegian deployment must
supply different school/calendar parsers and may need different activity,
weather and transit adapters.

## Development model

`dev` is the normal working branch; `main` is the tested production and
deployment branch. The lightweight promotion procedure is documented in
[`docs/BRANCHES.md`](docs/BRANCHES.md).

## Local family configuration

Git contains no household identities or delivery identifiers. Both FamilyBot
repositories carry the same canonical placeholder file at
[`config/family.example.json`](config/family.example.json). Install and edit
one shared local copy:

```bash
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
```

Replace every applicable uppercase placeholder and remove unused optional
second-location fields. Keep the populated file owner-readable:

```bash
chmod 600 "$HOME/.openclaw/workspace/config/family.local.json"
```

The file supplies family names, ages, grades/classes, Telegram recipients,
email routing addresses, Spond group IDs, home/optional second-location
coordinates and Entur preferences. `FAMILYBOT_FAMILY_CONFIG` overrides the file
path. `FAMILYBOT_WORKSPACE` or `OPENCLAW_WORKSPACE` overrides the workspace.

API tokens and credentials do **not** belong in this JSON file. OpenClaw/
Telegram credentials, the configured mail client's credentials and Spond
authentication remain in their respective ignored local credential stores.

Required and optional fields are documented in
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Runtime boundary

The live SQLite database, email attachments, OpenClaw memory, credentials, logs,
caches and database backups are runtime data and must never be committed. The
repository is restorable source, not a backup of private household state.

A complete clean-host restoration therefore needs both:

1. these Git repositories; and
2. a separate protected local backup of the workspace database, family config
   and external-service credentials.

See [`docs/REDEPLOY.md`](docs/REDEPLOY.md) for the ordered recovery checklist.

## Verification

```bash
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh
```

[`scripts/reliability.py`](scripts/reliability.py) owns atomic state, safe
SQLite access, idempotent delivery and retryable ingestion. The operational
invariants and promotion checklist are in
[`specs/RELIABILITY.md`](specs/RELIABILITY.md).
