# Redeploy and disaster recovery

Git restores reviewed source. A protected backup restores household state and
credentials. You need both.

## Backup inventory

- [ ] `familybot-core` and `familybot-portal` refs/tags
- [ ] `$HOME/.familybot/config/family.local.json` and `parent-pin.txt`
- [ ] `$HOME/.familybot/db/family.db` plus required attachments/memory
- [ ] OpenClaw provider and Telegram credential state, only for the agent profile
- [ ] Himalaya configuration/secret store, only when email is enabled
- [ ] `$HOME/.familybot/secrets.env` when Spond is enabled
- [ ] reviewed LaunchAgent schedules and any non-default environment overrides

Store runtime backup material encrypted and separately from Git.

## Clean-host restore order

1. Create the service user and install Command Line Tools, Homebrew Node.js
   22.22.3–22.x, `uv`, Python 3.12 and SQLite. Install OpenClaw, Himalaya and
   other optional clients only for capabilities present in the backup.
2. Clone `familybot-core` and `familybot-portal` as sibling directories. Check
   out the exact compatible Core/Portal commit pair recorded with the backup.
   The installer is currently a development candidate, not yet on main.
3. Restore `$HOME/.familybot` with directories mode `0700` and private
   files mode `0600`.
4. Verify the selected backup without replacing current state:

   ```bash
   sqlite3 "/exact/path/to/backup/family.db" \
     "PRAGMA integrity_check; PRAGMA foreign_key_check;"
   ```

5. Restore the database through the supported command, which verifies the
   source and preserves a pre-restore copy when a target already exists:

   ```bash
   cd familybot-core
   uv run --python 3.12 scripts/manage_database.py restore \
     --db "$HOME/.familybot/db/family.db" \
     --backup-root "$HOME/.familybot/backups" \
     --from-backup "/exact/path/to/backup/family.db"
   ```

6. Restore or create the one local family config and validate it with an
   explicit `FAMILYBOT_FAMILY_CONFIG` path.
7. Restore enabled credentials using [CREDENTIALS.md](CREDENTIALS.md). Test capability,
   never secret value.
8. For the agent profile only, audit and apply the OpenClaw default model before deployment:

   ```bash
   python3 familybot-core/scripts/configure_openclaw_model.py --apply --restart
   ```

   Prove access with one no-delivery agent turn; a configured catalog entry is
   not sufficient.
9. Rerun the idempotent installer. It applies compatible Core and Portal
   migrations and deploys the dashboard:

   ```bash
   uv run --python 3.12 scripts/install_familybot.py \
     --portal-repo ../familybot-portal
   ```

10. Run `scripts/check_setup.py --mode runtime --profile dashboard` (or the
    restored profile) and both repositories' verification suites.
11. For connected/agent profiles, deploy the selected Core jobs with
    `bash scripts/deploy_core.sh --reload`.
12. Run `python3 ../familybot-portal/tests/acceptance.py --workspace "$HOME/.familybot" --host TEST-MAC.local`
    with the actual configured hostname and selected restored workspace.
    Add `--allow-integrations` only with consent for configured adapter reads.
    Probe success does not certify browser/hardware/provider acceptance.
13. Verify an iPad child completion/parent rejection cycle where children are
    configured. Test email/Ukeplan, Spond, briefing preview, Telegram, weather
    and Entur only when each capability is enabled. Record disabled criteria
    as not applicable and unperformed checks as not run.

Optional add-ons such as Home Assistant are restored only after this base
pipeline is healthy. Their failure must not block core recovery. Follow the
separate acceptance and credential boundary in `specs/SMART_HOME.md` before
restoring appliance control.

## Upgrade an existing host

```bash
git -C familybot-core fetch --prune
git -C familybot-portal fetch --prune
git -C familybot-core switch --detach REVIEWED_CORE_SHA
git -C familybot-portal switch --detach REVIEWED_PORTAL_SHA
```

Replace the two SHA placeholders with the reviewed compatible pair from the
release/PR record; do not literally execute placeholder values. Record the
current pair first and create a consistent backup with
`scripts/manage_database.py backup` **before switching source**, then rerun
the installer. It migrates Core before Portal, refuses future/incompatible
schema versions and verifies the local services. Deploy connected/agent Core
jobs only after the Portal baseline is healthy.

## Rollback

1. Stop the affected LaunchAgent.
2. Keep the failed logs and database copy for diagnosis.
3. Restore the selected pre-migration SQLite backup with
   `scripts/manage_database.py restore` only when reverting a schema/data
   change requires it. Documentation and default-path fixes do not require
   database restoration; restoring unnecessarily would discard newer work.
4. Check out the last known-good tag/commit and redeploy generated runtime.
5. Restart and rerun health/acceptance checks.

Do not use Git rollback to restore private SQLite state.

## Recovery evidence and limits

Empty initialization, repeat installation, upgrade, migration failure rollback
and restore are automated tests. A clean-room CI run cannot prove the household's
router, iPad, mail provider, Spond account, Telegram bot, model entitlement or
experimental grocery-provider contract. Record those as manual verification,
not as inferred success.
