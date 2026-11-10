# OpenClaw setup checks and recovery

OpenClaw is optional. These checks apply to the Agent profile and separately
enabled Oda dinner AI, not a dashboard-only installation. A valid JSON schema
or reachable gateway does not prove that the model runtime can start.

## Read-only checklist

1. Record the installed OpenClaw and Codex versions and the reviewed Core ref.
2. Run `openclaw config validate`, `openclaw doctor --lint --all --json` and
   `openclaw security audit --json`. Flags depend on the installed version;
   consult its `--help`. Never run a broad repair/upgrade to silence warnings.
3. Run `python3 scripts/configure_openclaw_model.py --check`. In addition to the
   default and scheduled model pins, this checks an enabled local Codex plugin's
   configured executable (or `codex` on PATH). WebSocket app servers have no
   local executable check. The check executes no model, does not change config,
   and prints no secret values. Existing health/deployment callers use it too.
4. Inspect the actual gateway LaunchAgent command/environment, agent workspaces,
   model runtime mappings, disabled as well as enabled cron jobs, and launchd
   ownership. launchd does not inherit Terminal's PATH. Keep ingestion, morning
   briefings, delivery and SRE owned by launchd; never reactivate old cron copies.
5. Check that briefing/Ukeplan/dinner agents have minimal tools, no skills or
   elevated access, and the deny-list from their setup scripts. Preserve the
   explicitly trusted-operator boundary of the main conversational agent.
6. Run `openclaw secrets audit --check --json`. Prefer supported SecretRefs for
   static gateway/Telegram tokens, backed by an owner-only store. OAuth state is
   provider-managed, not a static secret to blindly migrate or revoke. SecretRefs
   do not isolate secrets from an unrestricted process running as the same user.

CLI output and backups can contain private identifiers. Publish a sanitized
finding summary, never full configuration, cron prompts or credential stores.

## Repair and prove

Back up configuration, the gateway service definition, cron definitions and
OpenClaw's own SQLite state with its SQLite backup API. Keep these owner-only,
outside Git. Do not back up a live SQLite file using a plain file copy. This is
separate from the household database; configuration repairs need no family-data
migration. Record the exact inverse of each change.

If a desktop update moved Codex, locate the installed executable and verify
`codex --version`. Update `plugins.entries.codex.config.appServer.command` to the
verified executable, validate configuration, and restart the gateway. Do not
hardcode another household's application bundle path in repository defaults.
Alternatively install the supported standalone Codex CLI deliberately; do not
silently install or upgrade it as part of a health check.

After restart, use a fresh session and fictional content for one bounded
no-delivery turn per enabled inference agent. For example:

```bash
openclaw agent --agent familybot-briefing --session-id "$(uuidgen)" \
  --message 'Do not use tools. Reply exactly: RUNTIME_OK' \
  --thinking low --timeout 45 --json
```

Do **not** add `--deliver`, run scheduled jobs, or replay outbox records during
verification. Confirm the exact response, not just exit zero. Repeat for the
Ukeplan agent and dinner agent only when enabled. Check gateway/channel health
and the next genuine scheduled result separately. Do not reset real outcome
counters merely because a connectivity smoke test passed.

An old plugin JSON index may conflict with an authoritative newer SQLite
registration. Verify the loaded plugin path/version before archiving that old
index. Retain a rollback copy. Likewise archive an old sent-message cache only
after proving its entries are migrated or older than the installed cache TTL.
Never delete active deduplication/delivery state to remove a diagnostic warning.
Pin reviewed compatible plugin versions. A newer registry version alone does
not justify upgrading the whole gateway; a requested matching patch may not
exist in the registry.

## Briefing behavior on inference failure

Daily model output is bounded to 1600 characters; weekly output to 3200.
Overlong output is rejected with the content-free `output_too_long` reason.
When inference fails, each stored plan is represented by the configured child's
name, available week number and an explicit unavailable-summary notice pointing
to the family portal. Neither raw PDF text nor a possibly truncated stored
summary is copied. Full source text remains stored and accessible in the plan
detail; source parsing/attribution are unchanged.

Important task/RSVP titles and other deterministic facts remain intact. An
exceptionally busy fallback may still require multiple Telegram parts; this is
not a hard one-message limit that discards obligations. Normal two-child fixture
fallbacks fit one part. Existing lossless splitting, atomic recipient queuing,
immutable retries, vacation suppression and delivery idempotency are unchanged.

## November 2026 regression record

- Evidence: a missing configured Codex executable caused inference failure;
  the old fallback copied full plans, producing three parts per recipient.
- Scope: Core runtime preflight and briefing presentation only. No schema,
  Portal, provider/model switch, permissions expansion or household-data repair.
- Tests: missing/existing executable, disabled/remote plugin, model failure,
  excessive output, named bounded plan references and retained important actions.
  Existing multipart/retry tests continue to apply.
- Rollback: restore the reviewed source files and backed-up OpenClaw config/
  service settings, restart the gateway, then run a no-delivery smoke test.
  Do not restore household SQLite for these code/config-only changes.
- Residual risks: plain-HTTP LAN dashboard, trusted main-agent filesystem/runtime
  access, upstream plugin/CLI compatibility, and provider account availability.
  A local check is not evidence of a physical iPad, live school PDF or scheduled
  delivery succeeding. Operator-specific evening jobs must use real schema
  columns (`spond_events.last_updated`, not `updated_at`), read-only database
  access and cached health; they must not duplicate SRE execution or alerts.
