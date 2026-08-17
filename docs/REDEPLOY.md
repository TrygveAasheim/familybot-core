# Clean-host redeployment

Git restores FamilyBot source, but deliberately excludes household state and
credentials. A complete recovery needs a protected local backup as well.

## Protected inputs required

- `$HOME/.openclaw/workspace/config/family.local.json`;
- `$HOME/.openclaw/workspace/db/family.db`;
- OpenClaw/Telegram credentials and configuration;
- mail-client configuration and credentials;
- Spond authentication state;
- attachments and operational memory that must survive a host loss;
- reviewed LaunchAgent definitions and schedules.

## Ordered restore

1. Install macOS Command Line Tools, Python 3.9+, OpenClaw, the configured mail
   client and the dependencies used by the PDF parsers.
2. Clone `familybot-core` and `familybot-portal`.
3. Restore `$HOME/.openclaw/workspace` and the protected SQLite database.
4. Check the database before starting jobs:

   ```bash
   sqlite3 "$HOME/.openclaw/workspace/db/family.db" "PRAGMA integrity_check;"
   ```

5. Restore the protected family config, or create it from the canonical template:

   ```bash
   install -d -m 700 "$HOME/.openclaw/workspace/config"
   install -m 600 config/family.example.json \
     "$HOME/.openclaw/workspace/config/family.local.json"
   ${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
   chmod 600 "$HOME/.openclaw/workspace/config/family.local.json"
   ```

6. Replace applicable uppercase placeholders and remove unused optional
   second-location entries. Do not put passwords, API tokens or session cookies
   in this file.
7. Restore and test OpenClaw/Telegram, mail and Spond credentials separately.
8. Validate the source against the supplied non-private fixture:

   ```bash
   FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
     python3 -m unittest discover -s tests -p 'test_*.py'
   python3 -m py_compile scripts/*.py
   bash -n scripts/*.sh
   ```

9. Back up the restored workspace, then deploy the reviewed scripts into
   `$HOME/.openclaw/workspace/scripts`.
10. Restore reviewed LaunchAgents and verify each scheduled command manually
    before enabling its interval.
11. Run health checks, an email/ukeplan test, a deterministic briefing preview
    and one Telegram delivery to each configured parent.

## Current automation boundary

The core repository does not yet contain a one-command installer for every
historical LaunchAgent. `ops/launchd/familybot.delivery.plist.example` covers
the retry worker; other production schedules must be restored from a protected,
reviewed operational backup until a complete installer is added.

## Path overrides

- `FAMILYBOT_WORKSPACE` or `OPENCLAW_WORKSPACE`: workspace root.
- `FAMILYBOT_FAMILY_CONFIG`: populated family JSON path.

launchd does not inherit interactive shell startup files. Add non-default
environment values explicitly to each plist.
