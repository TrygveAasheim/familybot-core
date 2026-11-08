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
weekday are read from `notifications` into launchd calendar fields. launchd uses
the Mac's system time zone, not `family.timezone`; there is no conversion.
Before enabling schedules, set the Mac's time zone to match `family.timezone`
(normally `Europe/Oslo`) so launches and Python's date/health calculations agree,
including daylight-saving changes. The installer does not check this alignment.

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
export FAMILYBOT_WORKSPACE="$HOME/.familybot"
export FAMILYBOT_FAMILY_CONFIG="$FAMILYBOT_WORKSPACE/config/family.local.json"
export FAMILYBOT_DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
bash scripts/deploy_core.sh --reload
```

Use the installed workspace/config paths for a legacy household, not these
new-install defaults. Run from the reviewed Core checkout; the ref override
permits that selected Main/Dev/detached release without bypassing checks.

The deploy script creates/synchronizes the isolated Python 3.12 Core runtime,
copies reviewed core scripts into the private workspace, validates all ten
available templates, then invokes the installer. The installer is
intentionally explicit about the reload. It replaces only the source-controlled
`familybot.*.plist` jobs, keeps runtime state outside Git and prints the
installed labels without printing configuration or credential values.

Every integration is optional. A missing block or `"enabled": false` removes
its LaunchAgent and health/freshness expectation on the next deliberate
`--reload`. Spond additionally requires at least one configured group.

## Retire duplicate legacy Unix cron briefings

Older installations may still have direct `python3 .../scripts/briefing.py`
entries in the user's Unix crontab. They bypass the managed runner's command
path and lock, may run at different times, and can overwrite quality observations
or queue unwanted briefing runs. A launchd deployment does not remove them.
The agent health check reports this separately as `briefing_schedule`.

Audit from the reviewed Core checkout, using the actual installed workspace:

```bash
uv run --python 3.12 scripts/briefing_schedule.py --workspace /exact/installed/workspace
```

The default command is read-only and prints counts and an audit digest, not cron
commands or household content. Only after authorizing a schedule change, outside
an active briefing run, replace `AUDIT_SHA256` below with that audit's digest:

```bash
uv run --python 3.12 scripts/briefing_schedule.py \
  --workspace /exact/installed/workspace \
  --apply --expected-sha256 AUDIT_SHA256
```

Apply requires loaded managed jobs pointing to the same workspace/runner/task
(both weekday and weekend for a legacy daily entry, weekly for a weekly entry).
It comments only exact recognized direct-Python entries; ambiguous shell commands
require manual review. Unrelated lines are preserved. Before installing, it saves
the exact original crontab to a private `backups/legacy-briefing-cron-*/crontab.txt`
and rechecks for concurrent changes; it verifies the installed text afterward.
Cron has no compare-and-swap operation: avoid concurrent crontab editing during
this short operation. On timeout or verification failure inspect current state
and the backup before retrying. Do not blindly overwrite newer unrelated edits.

No database, outcome record, provider configuration or launchd job is changed,
and no briefing is replayed. The existing fallback warning clears after that
stream next generates successfully or its observation expires; it must not be
manually marked successful. Old poll-based counts do not become new-generation
counts. For rollback, review the private backup and restore only the intended
entries, preserving subsequent unrelated edits; restoring them reintroduces the
duplicate-schedule defect. Keep backups out of Git.

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
