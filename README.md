# FamilyBot 🇳🇴

FamilyBot is a local-first family information service for a Norwegian household.
An always-on Mac mini processes school email and `ukeplan` PDFs, Spond,
Norwegian calendar data, MET weather and Entur transport; OpenClaw provides the
conversational/Telegram layer; Familieportalen provides the iPad-first touch UI.

> **Norway-first:** the reliability layer and dashboard model are reusable, but
> the current school, calendar, transport and activity adapters assume Norwegian
> language and services, with Oslo school-calendar data.

## What is in this repository

- deterministic email/PDF routing and weekly-plan extraction;
- Spond synchronization through an unofficial community client;
- Norwegian calendar, weather and transport inputs;
- SQLite reliability primitives, ingestion ledger and delivery outbox;
- launchd-compatible scheduled jobs, health and status reporting;
- the **one canonical family configuration template**.

The sibling `familybot-portal` repository contains the responsive LAN dashboard.
Inference may improve family-facing wording, but it is not part of the
durability boundary.

## Start here

1. [New-user walkthrough](GETTING_STARTED.md)
2. [Architecture and Mac mini/iPad topology](ARCHITECTURE.md)
3. [Canonical configuration](CONFIGURATION.md)
4. [Credential/token checklist](CREDENTIALS.md)
5. [Security and OWASP posture](SECURITY.md)
6. [Redeploy and disaster recovery](REDEPLOY.md)

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
python3 scripts/validate_config.py \
  --config config/family.example.json --allow-placeholders --skip-permissions
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh
```

Runtime SQLite, email attachments, credentials, OpenClaw memory, logs and
backups are deliberately excluded from Git. Git is a source backup, not a
household-state backup.

## Development and release

`dev` is the normal working branch. Tested commits are fast-forwarded to
`main`, which is the deployment branch. See [docs/BRANCHES.md](docs/BRANCHES.md)
and [specs/RELIABILITY.md](specs/RELIABILITY.md).
