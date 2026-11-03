# Changelog

Material security, reliability and compatibility changes are recorded here.
Household data, credentials and operational identifiers are never included.

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
