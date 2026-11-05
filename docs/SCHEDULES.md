# Scheduled jobs

FamilyBot schedules are owned by macOS `launchd`. The reviewed source templates
live in [`ops/launchd/`](../ops/launchd/), and the installer expands the
`__FAMILYBOT_WORKSPACE__` token for the current machine.

`launchd` weekday values are Sunday `0` or `7`, Monday `1`, through Saturday
`6`. The briefing contract is:

| Job | Default | Profile / condition |
| --- | --- | --- |
| Email ingestion | every 15 minutes | Connected/Agent with email |
| Spond synchronization | every 60 minutes | Connected/Agent with configured groups |
| Entur disruption monitor | every 15 minutes | Connected/Agent with transport |
| Health + bounded SRE reconciliation | every 30 minutes | Connected/Agent |
| Status snapshot | every 30 minutes | Connected/Agent |
| Weekday morning briefing | Monday–Friday 06:45 | Agent when enabled |
| Weekend morning briefing | Saturday/Sunday 08:00 | Agent when enabled |
| Weekly overview | Sunday 21:00 | Agent when enabled |
| Delivery retry worker | every 5 minutes | Agent |
| Ukeplan interpretation | every 15 minutes | Agent with email |

The Dashboard profile installs none of these jobs. Briefing times and weekly
weekday are read from `notifications` and interpreted in `family.timezone`,
including daylight-saving transitions.

Validate the templates before installation:

```bash
python3 scripts/validate_launchd.py
```

Install the reviewed templates without restarting jobs:

```bash
bash scripts/install_launchagents.sh
```

For a deliberate deployment and reload of the affected LaunchAgents:

```bash
bash scripts/deploy_core.sh --reload
```

The deploy script creates/synchronizes the isolated Python 3.12 Core runtime,
copies reviewed core scripts into the private workspace, validates all ten
available templates, then invokes the installer. The installer is
intentionally explicit about the reload. It replaces only the source-controlled
`familybot.*.plist` jobs, keeps runtime state outside Git and prints the
installed labels without printing configuration or credential values.

Every integration is optional. A missing block or `"enabled": false` removes
its LaunchAgent and health/freshness expectation on the next deliberate
`--reload`. Spond additionally requires at least one configured group.

## Monitoring and bounded recovery

`cron_runner.sh` records each job's start, finish and exit state under the
private workspace. `healthcheck.py` uses that state and each job's expected
schedule, so a stale weekend exit is reported as historical evidence rather
than a new failure on every poll.

The health job invokes `scripts/sre_reconcile.py`. Its recovery allowlist is
limited to missing or overdue interval workers and repeated gateway failures.
Actions are cooldown-limited and written to the owner-only
`db/sre-actions.jsonl` audit log. Daily, weekend and weekly briefings are
never automatically replayed. Preview recovery with:

```bash
python3 scripts/sre_reconcile.py --dry-run
```

Database corruption, credentials, external API changes and persistent gateway
failures remain escalation cases rather than destructive automatic repairs.

SRE also owns `db/health_failures.json` and the transition-based Telegram alert
path. The separate OpenClaw conversational health-alert cron must remain
disabled; it previously re-read stale counters and produced duplicate warnings
even when the structured health snapshot was green. Set
`FAMILYBOT_SRE_ALERT_TARGET` only when the first configured parent is not the
desired owner alert recipient.
