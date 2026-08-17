# FamilyBot Core

Deterministic, self-hosted family-operations services for OpenClaw: email
ingestion and routing, weekly-plan parsing, Spond synchronization, weather and
transport collection, durable Telegram delivery, health checks, and status.

## Privacy boundary

Git contains no household identities or delivery identifiers. Copy
`config/family.example.json` to
`~/.openclaw/workspace/config/family.local.json`, replace every input parameter,
and keep the resulting file owner-readable (`chmod 600`). The local file is the
only source for member names, ages, school grades, Telegram recipients, email
addresses, Spond group IDs, locations, and local transport preferences.

The live SQLite database, attachments, memory, credentials, logs, caches, and
database backups are runtime data and must never be committed.

## Verification

```bash
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh
```

`scripts/reliability.py` owns atomic state, safe SQLite access, idempotent
delivery, and retryable ingestion. Inference may improve presentation, but it
is not part of the durability boundary.
