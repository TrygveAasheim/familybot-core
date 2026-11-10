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
- State/deployment: this change was refreshed onto the `dev` source baseline and
  approved for the development release train. No live sends, model calls,
  database repair or runtime configuration change is required to test it.

## Acceptance and tests

`tests/test_outcome_health.py` covers:

- missing child names/internal identifiers/action titles reject generated text;
- deterministic daily/weekly fallback retains named plan references, tasks and
  RSVP titles, without copying PDF text (see the November compact-fallback
  correction in [setup checks](OPENCLAW_SETUP_AUDIT.md));
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

Historical verification after rebasing onto `dev` (2026-11-05; not the final
installation train totals):

```text
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json python3 -m unittest discover -s tests -p 'test_*.py'
  PASS: 95 tests
python3 scripts/validate_config.py --config config/family.example.json --allow-placeholders --skip-permissions
  PASS: zero warnings
python3 scripts/validate_docs.py
  PASS: 23 Markdown files
python3 scripts/validate_launchd.py
  PASS: 10 templates
python3 -m py_compile scripts/*.py
  PASS
bash -n scripts/*.sh
  PASS
git diff --check
  PASS
```

## Operating policy

### 2026-11-08: duplicate schedule and false failure-count correction

An observed incident had legacy Unix cron and managed launchd briefings running
alongside each other. The legacy invocation lacked the working runtime command
path and wrote a weekly fallback observation while managed daily generation
succeeded. Three later health polls were incorrectly described as three
briefing failures. Delivery is a separate signal: check the outbox, never infer
delivery success or failure from the generation record.

The correction adds a read-only `briefing_schedule` health result and an explicit,
backed-up retirement tool documented in [SCHEDULES.md](SCHEDULES.md). It does not
rewrite live cron automatically, switch models, replay briefings, clear outcome
files or alter outbox rows. Source publication alone does not repair a host's
legacy schedules. This incident was triaged with bounded read-only diagnostics;
no runtime deployment or cron mutation was part of the fix preparation.

`memory/briefing-outcome-daily.json` and
`memory/briefing-outcome-weekly.json` hold the latest generation observation.
Daily observations remain relevant for two days; weekly ones for eight.
Absent observations are neutral during rollout; existing scheduler checks own
missing/stale jobs. A fallback warning indicates degraded generation, **not**
failed delivery. The outbox remains authoritative for delivery.

`briefing_quality` counts actual consecutive fallback generations per enabled
daily/weekly stream and escalates at three, once per streak. Repeated health
polls never advance that count. Generation success resets only its own stream;
an expired record starts a fresh streak. Legacy boolean-only files contribute
one observation, ignoring inflated historical poll counts. Reason codes distinguish
empty model output from validation rejection without storing output or stderr;
neither code proves a specific provider outage. Disabled streams are ignored.
Unreadable telemetry, `briefing_schedule` conflicts and `ukeplan_quality` retain
the three-unhealthy-check threshold. Alert text distinguishes checks from actual
fallback briefings. Historical failures outside current/next
week do not alert. Missing interpretation rows for existing layout-bearing
plans require attention; pending/processing rows receive a one-hour grace.

On escalation, inspect private job/model diagnostics and resolved attribution.
Retry a verified plan explicitly with `interpret_ukeplan.py --plan-id ID`;
do not replay already-delivered briefings or change historical weeks blindly.
Do not change provider automatically.

Regression checks: `tests/test_briefing_alert_regression.py` reproduces the
one-record/three-poll bug, independent streams, recovery, legacy records, stale
observations, reason minimization and malformed telemetry.
`tests/test_briefing_schedule.py` covers read-only audits, exact target matching,
unrelated-job preservation, loaded replacement jobs, private backups and refusal
on changed/ambiguous crontabs. Tests use fictional temporary state and mocked
processes; they never install a real crontab or send Telegram messages.

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

For rollout: back up the database and deployed source, deploy from reviewed
`dev`, inspect one health cycle and the next scheduled briefing, and verify
recipient outbox states. Do not send a duplicate report merely to smoke-test.
Rollback by restoring the previous deployed scripts; no database rollback is
needed. The two new private observation files may remain inert after rollback.
