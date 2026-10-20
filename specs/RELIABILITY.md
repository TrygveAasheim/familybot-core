# Reliability foundation

Status: privacy-safe source baseline. Deployment state must be verified from the
running OpenClaw workspace and launchd; this document is not a live status file.

## Invariants

1. Structured family facts are collected without an LLM. Inference may improve
   wording, but an empty, malformed, or timed-out inference response must fall
   back to deterministic text.
2. A family message is queued for both parents before the first Telegram send.
   Each recipient has a stable idempotency key, bounded retry backoff, expiry,
   and a short delivery lease to prevent concurrent duplicate sends.
3. Vacation mode never records a skipped Telegram call as delivered.
4. An email is terminal only after required durable outputs exist. In particular,
   an email identified as an ukeplan remains retryable until a `week_plans` row
   has been stored.
5. Runtime state files are replaced atomically. Readers see either the previous
   complete document or the next complete document, never a partial JSON file.
6. Scheduled tasks have one owner (`launchd`), reject unknown task names, and
   recover stale PID locks left by a killed process.
7. Health checks expose pending/repeatedly failed deliveries and retryable email
   failures instead of reporting only gateway availability.
8. Health monitoring is schedule-aware: a historical failure of a calendar job
   is not counted as a new failure on every later health poll. Each execution
   has an owner-only state record with start time, finish time, duration and
   exit code.
9. SRE recovery is bounded and auditable. Only allowlisted interval jobs may be
   bootstrapped or kickstarted, actions have a cooldown, and calendar briefings
   are never automatically replayed.
10. SRE owns consecutive health-failure counters and transition-based Telegram
    alerts. The conversational cron layer must not interpret health snapshots,
    maintain a second counter or send duplicate alerts.

## New durable state

- `delivery_outbox`: pending/sending/sent/expired Telegram deliveries, attempts,
  retry time, expiry, lease and last error.
- `email_processing_state`: per-message stage, status, attempt count and last
  error. Existing `email_log` rows remain the legacy completion signal only when
  no ledger row exists.
- `db/job_state/*.json`: per-LaunchAgent execution state. These files contain
  task labels and timestamps only; they never contain message content or
  credentials.
- `db/sre_state.json` and `db/sre-actions.jsonl`: cooldowns, repeated gateway
  failure counts and a privacy-safe audit trail of automatic recovery actions.
- `db/health_failures.json`: SRE-owned compatibility counters for the local
  health alert surface. They are reset from the current structured snapshot,
  not trusted as an independent source of truth.

Both tables are created idempotently by the code that owns them. SQLite
connections enable foreign-key enforcement and a 10-second busy timeout.

Ukeplan PDF layout evidence is stored with `week_plans.layout_json`. The
optional `week_plan_interpretations` row records a validated, source-backed
structured result separately from deterministic `week_plan_days` facts.

## Failure behaviour

- OpenClaw inference failure: render deterministic briefing, then queue it.
- One parent send succeeds and one fails: successful row stays sent; only the
  failed recipient retries.
- Sender process dies during delivery: the two-minute lease expires and another
  retry worker can reclaim the row.
- Telegram stays unavailable: exponential retry up to one hour, with daily and
  weekly expiry preventing stale briefings from arriving too late.
- An interval worker is missing or overdue: the SRE reconciler may bootstrap
  its owner-only LaunchAgent or kickstart it after the configured cooldown.
  Calendar jobs are reported for review instead of replayed automatically.
- The gateway fails two consecutive health observations: the reconciler may
  restart it once per cooldown, records the action and leaves persistent
  failures for escalation.
- Himalaya list/read fails: job exits non-zero; no message is marked processed.
- Attachment download or ukeplan parsing fails: ledger records the error and the
  email remains retryable.
- When an ukeplan PDF is present, only parsed PDF text may populate `week_plans`;
  the email body, headers, addresses and attachment metadata are never a
  fallback content source. Explicit child and valid ISO week/year metadata in
  a configured parent's subject overrides stale PDF headings. The resolved
  period controls deterministic day dates and interpretation validation.
- Ukeplan interpretation runs asynchronously after ingestion. An LLM may only
  produce accepted items whose text is present in stored PDF evidence and whose
  dates are in the plan's Monday–Friday ISO week. A timeout, malformed response,
  or validation failure leaves deterministic plan data available and is retried.
- A recent ukeplan was logged before a class mapping update: the bounded backfill
  resolves current 3A/6A content, repairs its member mapping and stores the plan.
- A Saturday/Sunday daily briefing: week-plan lookup rolls forward to Monday's
  ISO week while the displayed calendar date remains the current day.
- Briefing fallback uses configured child display names, preserves full stored
  PDF text rather than a character-truncated summary, and does not drop trailing
  sections to satisfy a line cap. Long text is split losslessly into numbered
  Telegram parts. All parts for each recipient are queued atomically and remain
  immutable on retry; both recipients are queued before sending. Retries send
  only unsent parts, never already delivered parts.

## Promotion checklist

1. Make a verified SQLite backup and a source snapshot.
2. Run the full unit suite against Python 3.9.
3. Run email ingestion against a copied database and fixture mailbox output.
4. Run daily and weekly briefing previews with OpenClaw unavailable.
5. Install `familybot.delivery` from the reviewed plist and verify its five-minute
   retry schedule.
6. Run `python3 scripts/sre_reconcile.py --dry-run` and inspect the proposed
   actions; it must not propose replaying a briefing.
7. Deploy source files, restart only the affected launchd jobs, and inspect the
   first health report plus `db/sre-actions.jsonl`.
8. Keep the previous source snapshot and database backup for rollback.
