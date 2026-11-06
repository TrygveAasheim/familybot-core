# Changelog

## 2026-11-06 — Upgrade preservation fixes (candidate, not deployed)

- Separate first installation from explicit stopped-writer upgrades, retaining
  installed workspace/runtime and existing PIN. Require deliberate grocery flags.
- Take a full verified pre-upgrade snapshot before any database changes, even
  without pending migrations; direct calendar maintenance also backs up first.
- Preserve database-only school calendars and omitted member metadata. Calendar
  replacement now requires an explicit list and `--replace-school-calendar`.
- Do not seed starter chores/rewards during upgrades. Existing 4–5 digit PINs
  remain accepted; new installations still require 6–8 digits.
- Restore recognized unversioned legacy backups without stamping new markers;
  reject tampered/future/unrelated sources and target SQLite sidecars.
- Add fictional upgrade regressions and extend disposable macOS managed CI
  with an upgrade/preservation check. Update setup, configuration, recovery,
  security and reliability instructions with the actual boundaries.

No new schema version or live deployment. Coordinate with Portal's transactional
validation/no-reseed fix and its consumed-Core-schema startup check (the
adversarial review found that a version marker could hide a missing calendar
table). Source-only rollback reverts the pair; if an upgrade
was run and data changes must be undone, stop all database users and restore the
full pre-upgrade snapshot plus the matching old source/configuration. Individual
component transactions do not undo earlier installer steps. See `REDEPLOY.md`.

## 2026-11-06 — Double-review follow-up (candidate, not deployed)

- Give dashboard readiness a bounded ten-second request timeout, covering the
  sequential four-second MET and Entur failure paths; keep other probes at two
  seconds and retain identity, origin and same-instance checks.
- Quote every scheduler interpreter invocation so explicit workspace/runtime
  paths containing spaces work, including failure reporting and SRE dispatch.
- Correct detached-release Core deployment instructions in the recovery guide.
- Add slow-response HTTP, route-budget, isolated scheduler dispatch/exit-code
  and detached/branch recovery-ref regressions. No schema or data migration.

Roll back this follow-up by reverting its source commit; no database restore
is needed. Runtime deployment is separate and not authorized by this PR train.

Material security, reliability and compatibility changes are recorded here.
Household data, credentials and operational identifiers are never included.

## 2026-11-06 — Installation review fixes (candidate, not deployed)

- Aligned Python/shell workspace defaults with `.familybot`, retaining explicit
  legacy overrides and rejecting conflicting installer config/database paths.
- New wizard/demo installs use the Mac's existing local hostname. Verification
  checks FamilyBot identity, configured Origin, authenticated dashboard and web
  content on loopback and requires the hostname to reach the same API session.
- Added actual HTTP chore/parent-approval/restart/reinstall tests and isolated
  macOS managed deployment/restart CI with test-owned labels and cleanup.
- Corrected candidate branch instructions, optional AI consent, recovery and
  acceptance claims across the documentation. The F1–F8 plan and hardware gate
  are in `docs/READINESS_FIX_PLAN.md` and `docs/INSTALLATION_READINESS.md`.

No schema change or production deployment. Revert the coordinated source pair
to roll back; no database restore is needed for this change. Old installations
must retain their explicit workspace path; omitted grocery flags in Portal now
mean disabled and must be enabled deliberately if wanted.

## 2026-11-05

### Independent household installation

- Added authoritative Core schema version 1, transactional migrations, a
  shared component/checksum ledger and verified backup/restore commands.
- Added an idempotent macOS installer that creates a private `$HOME/.familybot`
  workspace, empty database, fictional demo household and compatible Portal
  schema without an owner-provided starter database.
- Added Dashboard, Connected and Agent capability profiles. Deployment, health,
  status and schedules now omit disabled integrations instead of reporting
  them as failures.
- Split deployed PDF and unofficial Spond dependencies into adapter-specific,
  hash-locked sets so a household installs only capabilities it enabled.
- Replaced fixed school dates with configured municipality calendars and
  calculated Norwegian public holidays; notification schedules and processing
  use the configured IANA time zone.
- Made member display and school-profile updates repeatable by stable member
  ID, with a verified pre-change backup and preserved Kanban assignments;
  incompatible role changes fail before household identity is rewritten.
- Added clean-room, migration-failure, restore, profile-schedule and macOS CI
  coverage.

Existing databases are compatible and receive a verified backup before their
first recorded Core migration. New installs default to `$HOME/.familybot`;
existing installations may keep their current workspace path. Roll back source
and restore the automatic pre-migration backup with
`scripts/manage_database.py restore` if a migration must be reversed.

### Outcome reliability safeguards

- Reject briefing inference that omits configured child names or required
  important task and RSVP titles, then deliver the complete deterministic
  fallback instead.
- Preserve upcoming events, evening advice, secondary-location forecasts and
  important parent actions in deterministic briefing output.
- Report recent briefing fallback and blocked current/next-week Ukeplan
  interpretation as content-free health signals owned by the existing SRE
  counter and alert loop.
- Make failed Ukeplan interpretation attempts exit non-zero, reject stored
  attribution conflicts before inference and validate parsed ISO dates before
  mutating plan rows.

These outcome-reliability changes add no migration beyond the installation
schema work above and no credential migration. Deployment adds two optional,
owner-only briefing outcome files; rollback may leave them inert on disk.

### Repository maintenance

- Directed future Dependabot pull requests to the `dev` integration branch so
  dependency changes follow the documented review and deployment flow.

## 2026-11-03

### Security and quality hardening

- Replaced shell-based health probes with fixed argument-vector subprocesses.
- Removed the unused dynamic-execution weekly briefing wrapper; the reviewed
  `cron_runner.sh` entry remains the only weekly schedule path.
- Restricted the Entur setup helper to the fixed HTTPS provider origin.
- Isolated briefing and school-plan inference from the general-purpose agent;
  both now run through dedicated agents with all tools, skills and elevation
  disabled.
- Removed the unused generic LLM wrapper that still targeted the general agent.
- Added regression coverage for command-execution and provider-origin
  boundaries.
- Added mandatory Ruff, Bandit and pip-audit gates to Core CI.
- Added a Python 3.12 Ruff baseline and cleared all existing E/F/I findings.
- Hash-locked the resolved Python runtime and CI security-tool dependency sets.
- Pinned and explicitly allowlisted the deployed Codex OpenClaw plugin; the
  plugin audit now reports no unpinned install record.
- Prevented a warning exit from the health job from recursively appearing as a
  new scheduler failure; crashes and other interval-job failures remain active.
- Captured the deployed subway-notification repair in source: provider fetch
  failures preserve the previous cache, cosmetic notice edits are deduplicated,
  and durable notification history prevents repeated Telegram alerts.

There is no database, credential or household-state migration. Roll back by
redeploying the preceding source commit; private state remains compatible.
