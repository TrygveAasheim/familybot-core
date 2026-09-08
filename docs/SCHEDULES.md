# Scheduled jobs

FamilyBot schedules are owned by macOS `launchd`. The reviewed source templates
live in [`ops/launchd/`](../ops/launchd/), and the installer expands the
`__FAMILYBOT_WORKSPACE__` token for the current machine.

`launchd` weekday values are Sunday `0` or `7`, Monday `1`, through Saturday
`6`. The briefing contract is:

| Job | launchd weekdays | Time | Command |
| --- | --- | --- | --- |
| Weekday morning briefing | `1–5` | 06:45 | `briefing-daily` |
| Weekend morning briefing | `0` and `6` | 08:00 | `briefing-daily` |
| Weekly overview | `0` | 21:00 | `briefing-weekly` |
| Delivery retry worker | interval | every 5 minutes | `delivery` |
| Ukeplan interpretation | interval | every 15 minutes | `ukeplan-interpret` |

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

The deploy script copies reviewed core scripts into the private workspace,
validates the templates, then invokes the installer. The installer is
intentionally explicit about the reload. It replaces only the source-controlled
`familybot.*.plist` jobs, keeps runtime state outside Git and prints the
installed labels without printing configuration or credential values.

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
