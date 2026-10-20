# Outcome safeguards: review and rollout

## Change record

- Change type: core-critical bug fix and reliability improvement.
- Problem: a failed interpretation returned exit code zero; successful delivery
  obscured fallback generation; generated messages could omit child names and
  important action titles.
- Evidence: interpreter failure regression now requires exit code one; quality
  fixtures reproduce name/action omissions and disagreement between parsed
  dates and the authoritative subject period.
- Owner/scope: Core ingestion, interpretation, briefing and existing SRE health
  loop. No Portal/API change, new schedule, provider switch or schema migration.
- Privacy: quality records contain no child names, prompts, email text, message
  text, destinations or credentials. Raw model stderr is no longer printed by
  briefing generation. Existing private interpretation diagnostics are unchanged.
- State/deployment: this change is prepared on a feature branch for owner review;
  do not merge or deploy until approved. No live sends, model calls, database
  repair or runtime configuration change is required to test it.

## Acceptance and tests

`tests/test_outcome_health.py` covers:

- missing child names/internal identifiers/action titles reject generated text;
- deterministic daily/weekly fallback retains plan text, tasks and RSVP titles;
- failed telemetry persistence does not prevent delivery;
- owner-only, content-free observation records, recovery and stale observations;
- current versus historical interpretation failures and one-hour pending grace;
- SRE alert threshold, deduplication and recovery;
- inconsistent parser period/dates rejected before opening the database.

`tests/test_ukeplan_interpretation.py` covers non-zero failed-attempt exit,
durable failed status, preserved original plan and no automatic repeated model
calls. Existing subject/briefing regressions cover subject precedence, old-week
preservation, multipart integrity and recipient-specific retries.

Run the full `AGENTS.md` verification commands. Tests mock model/Telegram calls
and use temporary databases/state; never use the production workspace for tests.

Verification on the feature branch (2026-10-20):

```text
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json python3 -m unittest discover -s tests -p 'test_*.py'
  PASS: 65 tests
python3 scripts/validate_config.py --config config/family.example.json --allow-placeholders --skip-permissions
  PASS: zero warnings
python3 scripts/validate_docs.py
  PASS: 21 Markdown files
python3 -m py_compile scripts/*.py
  PASS
bash -n scripts/*.sh
  PASS
git diff --check
  PASS
```

## Operating policy

`memory/briefing-outcome-daily.json` and
`memory/briefing-outcome-weekly.json` hold the latest generation observation.
Daily observations remain relevant for two days; weekly ones for eight.
Absent observations are neutral during rollout; existing scheduler checks own
missing/stale jobs. A fallback warning indicates degraded generation, **not**
failed delivery. The outbox remains authoritative for delivery.

`briefing_quality` and `ukeplan_quality` participate in the existing three-check
SRE escalation policy. Messages are stable so unchanged failures do not reset
the threshold or repeatedly alert. Historical failures outside current/next
week do not alert. Missing interpretation rows for existing layout-bearing
plans require attention; pending/processing rows receive a one-hour grace.

On escalation, inspect private job/model diagnostics and resolved attribution.
Retry a verified plan explicitly with `interpret_ukeplan.py --plan-id ID`;
do not replay already-delivered briefings or change historical weeks blindly.
Do not change provider automatically.

## Risk assessment and next PRs

This is a deliberately bounded first PR, not a claim of complete self-healing.
Regression risk is moderate because ingestion and delivery selection are
core-critical. No migration or network retry policy changes are introduced.
Exact action-title checks are conservative: a valid paraphrase may trigger a
longer deterministic message. Multipart delivery already handles longer text.
Name/title checks cannot prove semantic completeness or correct homework
interpretation; source-backed interpretation validation remains necessary.

Separate follow-ups should cover:

1. A cached scheduled model capability probe, with explicit cost, timeout,
   frequency and unavailable-model tests. This PR observes real briefing
   failures, not pre-emptive model retirement.
2. Transient error classification and a finite inference retry budget. Keep
   permanent validation/auth/model errors out of automatic retry loops.
3. Expected-plan arrival monitoring with configured school holidays and
   per-child deadlines; absence alone is not yet an alert.
4. Richer semantic section validation and versioned plan history. Existing
   same-week revisions still replace the row; this PR protects period/date
   consistency, not a complete audit history.

After approval: back up the database and deployed source, deploy from reviewed
`dev`, inspect one health cycle and the next scheduled briefing, and verify
recipient outbox states. Do not send a duplicate report merely to smoke-test.
Rollback by restoring the previous deployed scripts; no database rollback is
needed. The two new private observation files may remain inert after rollback.
