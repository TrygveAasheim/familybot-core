# New-user walkthrough

This is the path a new household should be able to follow after forking both
repositories. It deliberately separates reproducible source from private data.

## 1. Understand the product boundary

FamilyBot Core ingests and normalizes family information. Familieportalen is
the iPad/touch UI. OpenClaw is the conversational and Telegram layer. SQLite is
the durable source of truth. Git does not contain your household database,
names or credentials.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md) and
[CREDENTIALS.md](CREDENTIALS.md) before exposing the service to the LAN.

## 2. Prepare the host

Use a dedicated, non-admin macOS account on an always-on Mac when practical.
Install Command Line Tools, Homebrew Node.js 22+, Python 3.9+, SQLite, OpenClaw
and Himalaya. Clone sibling directories:

```text
familybot-core/
familybot-portal/
```

Install dependencies:

```bash
cd familybot-core
python3 -m pip install -r requirements.txt

cd ../familybot-portal
npm ci
```

## 3. Add private inputs

Create the one local file from `familybot-core/config/family.example.json` and
follow [CONFIGURATION.md](CONFIGURATION.md). Complete the
[credential checklist](CREDENTIALS.md). Keep both Git trees clean.

## 4. Restore or initialize data

For an existing household, restore `family.db` before starting any job. For a
new household, the current release still requires an initial core schema from a
supported FamilyBot workspace or reviewed migration; the portal migration alone
cannot create every historical core table. This is the largest remaining
turnkey-installation gap and is intentionally stated rather than hidden.

Validate an existing database:

```bash
sqlite3 "$HOME/.openclaw/workspace/db/family.db" "PRAGMA integrity_check;"
```

## 5. Preflight and test

```bash
cd familybot-core
python3 scripts/validate_config.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh

cd ../familybot-portal
npm run lint
npm test
```

## 6. Deploy carefully

Copy reviewed core scripts into the private workspace, install only the jobs
whose integrations are configured, then use the portal's local deploy script.
The current core repository has a delivery-worker plist example but not yet a
one-command installer for every historical schedule. Restore or author those
LaunchAgents deliberately; do not blindly enable jobs copied from another
household.

Follow [REDEPLOY.md](REDEPLOY.md) for the full order. Verify from both the Mac
and an iPad, then save `http://familie.local:3000/` to the iPad Home Screen.

## What a fork still needs to customize

- Norwegian school parsing and Oslo school-calendar data are not globally
  portable.
- Entur stop/quay IDs and MET coordinates are household-specific.
- Spond uses an unofficial community client and may break after upstream
  changes.
- Core database creation and the full LaunchAgent set are not yet one-command.
- Local HTTP assumes a trusted home LAN; untrusted networks need TLS/VPN.
- External smart-home, menu and camera integrations are ideas, not part of the
  supported deployment.

These are explicit product boundaries, not silent setup steps.
