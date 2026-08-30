# FamilyBot agent contract

This file is the mandatory entry point for coding agents and fresh development
sessions working in `familybot-core`. It applies to the entire repository.

## Read before changing anything

Read these files in order:

1. `README.md`
2. `docs/REPOSITORY_GUIDE.md`
3. `specs/RELIABILITY.md`
4. `ARCHITECTURE.md`
5. `SECURITY.md`
6. `docs/CHANGE_PROTOCOL.md`

For installation or configuration work, also read `CONFIGURATION.md`,
`CREDENTIALS.md` and `REDEPLOY.md`. For appliance work, read
`specs/SMART_HOME.md` before writing code.

## Non-negotiable boundaries

- Deterministic ingestion, normalized SQLite facts, durable delivery and health
  reporting are the reliability core. They must not depend on an LLM, Telegram,
  the portal, Home Assistant or any optional integration.
- Inference may improve wording only. Failure, timeout or malformed output must
  preserve deterministic processing and delivery.
- An email is not complete until every required durable output exists. An
  `ukeplan` email without a stored `week_plans` row remains retryable.
- A delivery is not successful until its recipient-specific outbox row is sent.
  Vacation suppression is never recorded as delivery.
- Runtime state and credentials belong under the private OpenClaw workspace,
  never in Git. Do not print secret values while testing.
- Add-ons consume curated interfaces. They do not reach into or repurpose the
  email ledger, delivery outbox, parser state or raw untrusted payloads.

## Change classification

Treat changes to `scripts/reliability.py`, `process_emails.py`,
`email_routing.py`, `parse_ukeplan.py`, `briefing.py`, `briefing_data.py`,
`flush_outbox.py`, `calendar_guard.py`, database schemas or launchd schedules as
**core-critical**. Back up relevant state, test failure paths and preserve every
invariant in `specs/RELIABILITY.md`.

External adapters such as Spond, MET and Entur are **bounded adapters**. They may
fail independently and must return an honest unavailable/stale state rather
than corrupting shared facts.

The portal, chores, rewards, Smart Home, cameras, menus and other household
conveniences are **add-ons**. Keep their code and schemas isolated unless a
reviewed, generic interface is deliberately promoted into core.

## Required verification

Run at least:

```bash
python3 scripts/validate_docs.py
python3 scripts/validate_config.py \
  --config config/family.example.json --allow-placeholders --skip-permissions
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh
git diff --check
```

Run the additional risk-specific checks in `docs/CHANGE_PROTOCOL.md`. Do not
deploy from an unverified feature branch. Normal work is committed and
deployed from `dev`; `main` only receives pull requests reviewed and approved
by `@TrygveAasheim`.

## Documentation duty

If a change alters behaviour, configuration, security, deployment, a data
contract or an acceptance criterion, update the corresponding Markdown in the
same commit. Documentation that disagrees with the code is a defect.
