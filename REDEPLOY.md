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
     --from-backup "/exact/path/to/backup/family.db" --writers-stopped
   ```

6. Restore or create the one local family config and validate it with an
   explicit `FAMILYBOT_FAMILY_CONFIG` path.
7. Restore enabled credentials using [CREDENTIALS.md](CREDENTIALS.md). Test capability,
   never secret value.
8. For the agent profile only, audit and apply the OpenClaw default model before deployment:

   ```bash
   python3 scripts/configure_openclaw_model.py --apply --restart
   ```

   Prove access with one no-delivery agent turn; a configured catalog entry is
   not sufficient.
9. With all database users stopped, run the explicit upgrade path if the selected
   release includes this installer. Old releases use their own deployment procedure.
   This applies compatible Core/Portal migrations and deploys the dashboard:

   ```bash
   uv run --python 3.12 scripts/install_familybot.py \
     --portal-repo ../familybot-portal \
     --workspace "$HOME/.familybot" \
     --portal-runtime "$HOME/.familybot/runtime/familybot-portal" \
     --upgrade --writers-stopped
   ```

10. Run `scripts/check_setup.py --mode runtime --profile dashboard` (or the
    restored profile) and both repositories' verification suites.
11. For connected/agent profiles, deploy the selected Core jobs from the
    reviewed Core checkout (including a detached release commit):

    ```bash
    export FAMILYBOT_DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
    bash scripts/deploy_core.sh --reload
    ```

    This authorizes only the currently selected reviewed ref; it does not
    bypass the deployment guard. Keep the restored workspace/config overrides
    explicit when they differ from the default paths.
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

Before switching source, record the current Core/Portal SHA pair and create a
consistent backup with `scripts/manage_database.py backup`. Replace the SHA
placeholders below with the next reviewed compatible pair. Do not run the
literal placeholder names.

Preflight is mandatory, especially for a legacy installation:

1. Record the actual workspace/database/config/PIN and Portal runtime paths,
   installed service labels and source pair. Legacy `.openclaw/workspace` stays
   where it is; pass it explicitly. Do not let the new `.familybot` default select
   another household. Retain a separately installed Portal runtime explicitly.
2. Review `portal.features`: set `oda`, `oda_ai`, `hellofresh` and
   `hellofresh_account` to deliberate booleans. Omitted flags no longer mean
   enabled. The managed installer refuses ambiguity rather than disabling a
   previously used feature silently. Preserve hostname/origins, ports and PIN.
3. Save private config, credential stores and installed service definitions
   encrypted outside Git, along with the exact source pair. SQLite backup alone
   does not restore any of those files or application code.
4. Stop every database user, including Core schedulers, Portal, agents and
   manually started workers. Use `launchctl bootout "gui/$(id -u)/EXACT_LABEL"`
   for each recorded loaded service; close manually started workers too. Do not
   blindly stop unrelated services. Confirm they are stopped. The installer does
   not discover/stop workers and `--writers-stopped` is only an acknowledgement.
5. Take a consistent SQLite backup, then select the reviewed source pair below.

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
the installer with explicit paths (replace these illustrative values):

```bash
cd familybot-core
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal \
  --workspace "/exact/existing/workspace" \
  --portal-runtime "/exact/existing/portal-runtime" \
  --upgrade --writers-stopped
```

Retain non-default `FAMILYBOT_PORTAL_LABEL`/`FAMILYBOT_LAUNCHAGENT_DIR` overrides
when installed that way. A noncanonical existing PIN file can be supplied with
`--parent-pin-source /exact/private/pin-file`; an existing canonical PIN cannot
be overwritten with a different value. Legacy 4–8 digit PINs remain usable;
choose 6–8 random digits for a new install.

The installer creates a full `pre-upgrade` backup before **any database write**,
then migrates Core before Portal. Component transactions are separate; a later
failure does not automatically undo earlier commits. Keep the printed backup
path. A backup failure stops before database changes. For a data-only rehearsal
on a fictional/disposable stopped copy, add `--no-deploy` (no runtime required).
Never rehearse against the live database. Deploy connected/agent Core jobs only
after the Portal baseline is healthy, retaining their existing workspace and
schedule configuration. Verify the physical iPad and each enabled integration
before declaring the household upgraded.

Upgrades do not run starter seeds or repair inactive default rewards. Omitted
member `grade`, `school` and `teacher` retain stored values; explicit `null`
clears them. Existing school dates remain unless the operator provides both
`school.calendar_events` and `--replace-school-calendar`. An explicit empty
list plus that flag clears school dates; national public holidays still refresh.
Direct `calendar_seed.py` follows the same replacement guard and backs up first.

## Rollback

1. Stop **all** database users, not just the failed LaunchAgent.
2. Keep the failed logs and database copy for diagnosis.
3. Restore the selected pre-migration SQLite backup with
   `scripts/manage_database.py restore --writers-stopped` only when reverting a schema/data
   change requires it. Documentation and default-path fixes do not require
   database restoration; restoring unnecessarily would discard newer work.
4. Check out the last known-good tag/commit and redeploy generated runtime.
5. Restart and rerun health/acceptance checks.

Do not use Git rollback to restore private SQLite state.

Restore accepts a recognized unversioned FamilyBot backup after integrity,
foreign-key and legacy identity checks, without stamping it as upgraded. Future,
tampered or unrelated backups are rejected. Portal version compatibility remains
the responsibility of the matching source pair. Restore refuses target
`-wal`, `-shm` or `-journal` files: close all clients cleanly and resolve/checkpoint
SQLite recovery with the matching release before retrying. Do not delete sidecars:
they may contain committed data. Absence of sidecars is not proof no writer exists;
the operator must maintain exclusive downtime through replacement and restart.

## Recovery evidence and limits

Empty initialization, repeat installation, upgrade, migration failure rollback
and restore are automated tests. A clean-room CI run cannot prove the household's
router, iPad, mail provider, Spond account, Telegram bot, model entitlement or
experimental grocery-provider contract. Record those as manual verification,
not as inferred success.
