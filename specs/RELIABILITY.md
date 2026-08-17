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

## New durable state

- `delivery_outbox`: pending/sending/sent/expired Telegram deliveries, attempts,
  retry time, expiry, lease and last error.
- `email_processing_state`: per-message stage, status, attempt count and last
  error. Existing `email_log` rows remain the legacy completion signal only when
  no ledger row exists.

Both tables are created idempotently by the code that owns them. SQLite
connections enable foreign-key enforcement and a 10-second busy timeout.

## Failure behaviour

- OpenClaw inference failure: render deterministic briefing, then queue it.
- One parent send succeeds and one fails: successful row stays sent; only the
  failed recipient retries.
- Sender process dies during delivery: the two-minute lease expires and another
  retry worker can reclaim the row.
- Telegram stays unavailable: exponential retry up to one hour, with daily and
  weekly expiry preventing stale briefings from arriving too late.
- Himalaya list/read fails: job exits non-zero; no message is marked processed.
- Attachment download or ukeplan parsing fails: ledger records the error and the
  email remains retryable.
- A recent ukeplan was logged before a class mapping update: the bounded backfill
  resolves current 3A/6A content, repairs its member mapping and stores the plan.
- A Saturday/Sunday daily briefing: week-plan lookup rolls forward to Monday's
  ISO week while the displayed calendar date remains the current day.

## Promotion checklist

1. Make a verified SQLite backup and a source snapshot.
2. Run the full unit suite against Python 3.9.
3. Run email ingestion against a copied database and fixture mailbox output.
4. Run daily and weekly briefing previews with OpenClaw unavailable.
5. Install `familybot.delivery` from the reviewed plist and verify its five-minute
   retry schedule.
6. Deploy source files, restart only the affected launchd jobs, and inspect the
   first health report.
7. Keep the previous source snapshot and database backup for rollback.
