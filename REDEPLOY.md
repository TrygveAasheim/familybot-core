# Redeploy and disaster recovery

Git restores reviewed source. A protected backup restores household state and
credentials. You need both.

## Backup inventory

- [ ] `familybot-core` and `familybot-portal` refs/tags
- [ ] `$HOME/.openclaw/workspace/config/family.local.json`
- [ ] `$HOME/.openclaw/workspace/db/family.db` plus required attachments/memory
- [ ] OpenClaw provider and Telegram credential state
- [ ] Himalaya configuration/secret store
- [ ] `$HOME/.openclaw/workspace/secrets.env` when Spond is enabled
- [ ] portal `runtime/parent-pin.txt`
- [ ] reviewed LaunchAgent schedules and any non-default environment overrides

Store runtime backup material encrypted and separately from Git.

## Clean-host restore order

1. Create the service user and install Command Line Tools, Homebrew Node.js 22+,
   Python 3.9+, SQLite, OpenClaw and Himalaya.
2. Clone `familybot-core` and `familybot-portal` as sibling directories. Check
   out a reviewed tag or `main`, not a moving development branch.
3. Install `familybot-core/requirements.txt` and run `npm ci` in the portal.
4. Restore `$HOME/.openclaw/workspace` with directories mode `0700` and private
   files mode `0600`.
5. Restore `family.db`; run:

   ```bash
   sqlite3 "$HOME/.openclaw/workspace/db/family.db" \
     "PRAGMA integrity_check; PRAGMA foreign_key_check;"
   ```

6. Restore or create the one local family config from
   `familybot-core/config/family.example.json`; run
   `python3 familybot-core/scripts/validate_config.py`.
7. Restore credentials using [CREDENTIALS.md](CREDENTIALS.md). Test capability,
   never secret value.
8. Run both repositories' unit/lint/build suites before installing services.
9. Back up the restored database, then copy reviewed core scripts to
   `$HOME/.openclaw/workspace/scripts` and restore reviewed LaunchAgents.
10. In `familybot-portal`, create/restore the parent PIN and run
    `bash scripts/deploy-local.sh`.
11. Run `python3 tests/acceptance.py`; require every critical criterion to pass.
12. Verify one email/ukeplan, one Spond poll if enabled, one deterministic
    briefing preview, one Telegram delivery to each parent, weather, Entur and
    an iPad child completion/parent rejection cycle.

## Upgrade an existing host

```bash
git -C familybot-core fetch --prune
git -C familybot-portal fetch --prune
git -C familybot-core switch main
git -C familybot-portal switch main
git -C familybot-core pull --ff-only
git -C familybot-portal pull --ff-only
```

Run preflight and all tests. Take a consistent SQLite backup before any
migration. Deploy portal last, run acceptance, then return development checkouts
to `dev` if that is your workflow.

## Rollback

1. Stop the affected LaunchAgent.
2. Keep the failed logs and database copy for diagnosis.
3. Restore the pre-migration SQLite backup if a migration changed data.
4. Check out the last known-good tag/commit and redeploy generated runtime.
5. Restart and rerun health/acceptance checks.

Do not use Git rollback to restore private SQLite state.

## Current non-automated boundary

The portal has a local deploy script and LaunchAgent. The core still lacks a
complete fresh-database migration and a one-command installer for all schedules.
Until those are implemented, retain reviewed operational LaunchAgents in the
encrypted recovery bundle and inspect every command/path on a new host.
