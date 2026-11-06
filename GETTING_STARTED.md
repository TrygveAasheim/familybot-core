# Install FamilyBot on a Mac mini

This is the canonical setup guide for both FamilyBot repositories. It is for a
new household that can copy Terminal commands but has no existing FamilyBot,
OpenClaw, database or credentials.

The shortest path is the **Dashboard** profile. It is independently useful and
installs no optional integration. School mail, Spond, AI, Telegram, Oda and
HelloFresh can be added later.

## 1. Know what will be installed

| Profile | Capabilities | Required accounts |
| --- | --- | --- |
| Dashboard | Family profiles, chores, rewards, Kanban and iPad dashboard; weather/transport only when configured | None |
| Connected organizer | Dashboard plus school email/PDFs, deterministic Ukeplan data, Spond and scheduled processing | Only the integrations selected |
| AI family agent | Connected organizer plus model-assisted interpretation, briefings and Telegram | OpenClaw-supported model account and Telegram |

Oda and HelloFresh are independent optional Portal features.

The default dashboard is served only on the home LAN. Do not create router port
forwards for ports `3000` or `8788`.

## 2. Install the baseline software

The managed appliance path is tested on macOS with this baseline:

| Software | Baseline | Needed for Dashboard |
| --- | --- | --- |
| macOS Command Line Tools | Current supported macOS | yes |
| Node.js | `22.22.3` through `22.x` | yes |
| Python | `3.12` through `uv` | yes |
| `uv` | current stable | yes |
| Git, SQLite, `rsync`, Bonjour and `launchd` | macOS / Command Line Tools | yes |
| Himalaya `1.2+` | current supported | connected email only |
| OpenClaw | reviewed current release | AI/Telegram or separately opted-in Oda dinner AI only |

Install Apple's tools:

```bash
xcode-select --install
```

Install [Homebrew](https://brew.sh/) if needed, then:

```bash
brew install node@22 uv
echo 'export PATH="$(brew --prefix node@22)/bin:$PATH"' >> "$HOME/.zprofile"
export PATH="$(brew --prefix node@22)/bin:$PATH"
uv python install 3.12
node --version
uv --version
sqlite3 --version
```

The Node version must be at least `22.22.3` and remain below `23`.
Log into the Mac desktop as the installation user before managed setup;
`launchctl` needs that user's GUI domain. SSH-only/headless bootstrap is not a
supported substitute. Keep the Mac awake for household service availability.

## 3. Clone both repositories

Keep the checkouts together and outside a cloud-synchronized folder:

```bash
mkdir -p "$HOME/FamilyBot"
cd "$HOME/FamilyBot"
git clone --branch codex/readiness-review-fixes https://github.com/TrygveAasheim/familybot-core.git
git clone --branch codex/readiness-review-fixes https://github.com/TrygveAasheim/familybot-portal.git
git -C familybot-core switch --detach REVIEWED_CORE_SHA
git -C familybot-portal switch --detach REVIEWED_PORTAL_SHA
```

Replace REVIEWED_CORE_SHA and REVIEWED_PORTAL_SHA above with the full paired
commit IDs in the readiness PR handoff before running the commands; they are
not literal Git refs. Do not install a moving head without reviewing the pair.
This guide describes the development installation candidate. The public `main`
branch does not yet contain this installer. Before a main release, use the
paired reviewed candidate commits, not default clones. Pre-merge fixes are on
`codex/readiness-review-fixes` in both repos; the PR handoff records exact SHAs.
For a reproducible test, fetch that branch then `git switch --detach SHA` in
each checkout using its respective recorded SHA. Do not mix release tracks.
The directories must be siblings:

```text
$HOME/FamilyBot/familybot-core
$HOME/FamilyBot/familybot-portal
```

Optionally verify the source-only prerequisites before creating private state:

```bash
cd "$HOME/FamilyBot/familybot-core"
uv run --python 3.12 scripts/check_setup.py --mode source --profile dashboard
```

## 4. Install the dashboard

Run the guided installer:

```bash
cd "$HOME/FamilyBot/familybot-core"
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal
```

It asks for the family name, 1–20 parents and 0–20 children, optional school
and class, and a six-to-eight-digit parent PIN. It then:

1. validates macOS, Node, Python, Git, SQLite, `uv`, `rsync`, Bonjour and
   `launchd` before changing state;
2. creates `$HOME/.familybot` with owner-only directories and files;
3. writes the Dashboard profile with every integration disabled;
4. creates `family.db` from authoritative versioned migrations;
5. seeds household rows and starter chores;
6. builds and deploys the Portal; and
7. verifies FamilyBot API identity, a session with the configured web Origin,
   authenticated dashboard data and web content through the configured hostname.

For a new wizard/demo config it uses the Mac's existing `LocalHostName.local`,
as returned by `scutil --get LocalHostName`. It never renames your Mac.
`--hostname YOUR-LOCAL-HOSTNAME` overrides that choice for a new installation.
Supplied and existing configs keep their explicit hostname and origins. The
Bonjour service advertisement does not create a `familie.local` alias.

The operation is repeatable, but an existing database requires the explicit
upgrade procedure in section 11. A plain installer rerun stops without changing
that database. Upgrades preserve config/PIN, omitted member metadata, stored
school dates, archived chores and disabled rewards; starter data is first-install
only. An upgrade can change runtime behavior: it is not just a documentation update.

### Try fictional data first

Use the built-in Familien Nordlys demo:

```bash
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal --demo
```

The demo contains fictional people, schools, calendar dates, rewards and chores.
It makes no external integration request.

### Initialize without starting services

For review, CI or a disposable test workspace:

```bash
printf '482731\n' > /tmp/familybot-demo-pin
chmod 600 /tmp/familybot-demo-pin
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal \
  --workspace /tmp/familybot-demo \
  --demo --non-interactive --no-deploy \
  --parent-pin-source /tmp/familybot-demo-pin
```

Delete only that explicit disposable `/tmp/familybot-demo` directory when
finished. Never use a broad home-directory deletion command.

## 5. Open the dashboard

On the Mac, open the exact URL printed by the installer (for example
`http://kitchen-mac.local:3000/`, if that is your Mac's local hostname).

On the iPad, join the same trusted Wi-Fi and open the same URL in Safari. Use
Safari's **Share → Add to Home Screen** to create an app-like icon.

If Bonjour is unavailable, reserve the Mac's LAN IP in your router, set
`portal.hostname` to that IP and add its exact web origin to
`portal.allowed_origins` before redeploying. Keep localhost origins for local
diagnostics. Do not add wildcards or an entire private address range. Changing
the hostname also changes the Oda callback; reconnect Oda after that change.

Verify the installed baseline without printing private values:

```bash
cd "$HOME/FamilyBot/familybot-core"
FAMILYBOT_WORKSPACE="$HOME/.familybot" \
FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json" \
uv run --python 3.12 scripts/check_setup.py --mode runtime --profile dashboard
```

This is a software check, not evidence of a physical iPad test. Confirm touch,
portrait/landscape layout and parent approval on the actual household iPad.

## 6. Personalize the dashboard

The installer writes `$HOME/.familybot/config/family.local.json`. It is mode
`0600` and outside Git. Edit and validate it with:

```bash
nano "$HOME/.familybot/config/family.local.json"
FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json" \
uv run --python 3.12 scripts/validate_config.py
```

See [CONFIGURATION.md](CONFIGURATION.md) for school calendars, MET coordinates,
Entur stop/quay selection, secondary locations and notification schedules.
Never put passwords, API tokens, provider cookies or the parent PIN in this
JSON file.

After a valid edit, follow section 11 to upgrade and verify the Portal. Stop
database users first. To deliberately replace existing school dates, additionally
pass `--replace-school-calendar`; an explicit empty `school.calendar_events`
list clears them only with that flag. Omitted calendars never clear stored dates.

## 7. Enable the Connected organizer

Only do this for integrations the household has chosen.

1. Change `profile` to `connected`.
2. Add an integration block with `"enabled": true` for email, Spond and/or
   transport/weather.
3. Validate the configuration.
4. Configure credentials outside Git.
5. Deploy Core's selected schedules.

### School email and PDF plans

Install and configure Himalaya:

```bash
brew install himalaya
himalaya account configure familybot
himalaya account doctor familybot
himalaya folder list --output json
```

Set `integrations.email.account` to that account label. Use a dedicated mailbox
or app password when the mail provider supports it. Unknown mail remains
untrusted and cannot invoke tools.

### Spond

Spond uses an unofficial community client. Add only the selected groups to the
configuration and place credentials in the owner-only store described in
[CREDENTIALS.md](CREDENTIALS.md). A Spond outage disables only Spond data.

### Deploy selected connected jobs

```bash
cd "$HOME/FamilyBot/familybot-core"
export FAMILYBOT_WORKSPACE="$HOME/.familybot"
export FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json"
export FAMILYBOT_DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
bash scripts/deploy_core.sh --reload
uv run --python 3.12 scripts/check_setup.py --mode runtime --profile connected
```

Profile-aware deployment installs only enabled jobs. Missing optional
credentials are reported as an integration failure; they do not stop the
dashboard or unrelated adapters. The isolated Core runtime also installs the
PDF and unofficial Spond dependency locks only when their corresponding
adapter is enabled.

## 8. Enable the AI family agent

OpenClaw is the optional conversational/Telegram boundary—not a prerequisite
for SQLite, the dashboard or `launchd`.

Install a reviewed OpenClaw release, keep its gateway on loopback and use its
guided OpenAI and Telegram setup. This is the **minimal OpenClaw footprint**:
one local gateway/CLI, one model-backed agent and the Telegram channel. Do not
enable browser tools, public gateway access or unneeded plugins.

```bash
npm install --global openclaw
openclaw onboard --flow quickstart --mode local --install-daemon
openclaw channels add --channel telegram
```

Change `profile` to `agent`, add parent Telegram targets, validate, then deploy:

```bash
cd "$HOME/FamilyBot/familybot-core"
export FAMILYBOT_WORKSPACE="$HOME/.familybot"
export FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json"
export FAMILYBOT_DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
bash scripts/deploy_core.sh --reload
uv run --python 3.12 scripts/check_setup.py --mode runtime --profile agent
```

The briefing and Ukeplan agents have tools, skills and elevation disabled.
External email/PDF text is treated as data, not instructions. Deterministic
fallbacks remain active when inference fails. Consequential conversational
actions use bounded commands and explicit confirmation.

## 9. Optional Oda and HelloFresh

Both are Portal features and neither changes the capability profile.

- Oda uses a hosted MCP/OAuth service. The Portal exposes only an allowlist of
  recipe/product/cart operations; checkout remains at Oda.
- HelloFresh is experimental and disabled by default. It uses an unsupported,
  reverse-engineered Norway provider contract for upcoming boxes, bounded meal
  selection and pause/resume. Provider changes may break it without notice.

Enable `oda: true` for Oda, and separately `oda_ai: true` only if you consent to
the bounded dinner request/preferences leaving home for model processing. Oda
search/cart works without AI; AI additionally needs the isolated OpenClaw dinner
agent even outside the Agent profile. Enable `hellofresh: true` for public menus
and additionally `hellofresh_account: true` for guarded account writes. Omitted
flags are false, including for older configs: deliberately add flags before
upgrading if you want to retain those previously implicit capabilities.

Enable only the corresponding booleans under `portal.features`, validate the
config and follow the explicit upgrade procedure in section 11. Managed upgrades
require all four feature flags as booleans, including explicit `false` choices.
Provider credentials remain outside Git. The
plain-HTTP LAN risk is especially important for HelloFresh first-use password
entry; use only a trusted, isolated LAN.

## 10. Back up before upgrades

Create and verify a private SQLite backup:

```bash
cd "$HOME/FamilyBot/familybot-core"
uv run --python 3.12 scripts/manage_database.py backup \
  --db "$HOME/.familybot/db/family.db" \
  --backup-root "$HOME/.familybot/backups"
```

Also back up, encrypted and outside Git:

- `$HOME/.familybot/config/`;
- `$HOME/.familybot/backups/` and the current database;
- enabled integration credential stores;
- the exact Core and Portal Git commit IDs.

Git is not a household-state backup.

## 11. Upgrade safely

Read [the upgrade preflight](REDEPLOY.md#upgrade-an-existing-host) first. Record
the installed paths, source pair, service labels and configuration. Stop **all**
Core/Portal/agent processes using this database, not only the web page. The
`--writers-stopped` option acknowledges that you did this; it does not stop them.
The example below is for the new `.familybot` layout. For a legacy installation,
substitute its actual workspace and Portal runtime; do not move state or accept
new defaults. Explicitly retain any custom hostname, ports, schedule and flags.

```bash
cd "$HOME/FamilyBot/familybot-core"
uv run --python 3.12 scripts/manage_database.py backup \
  --db "$HOME/.familybot/db/family.db" \
  --backup-root "$HOME/.familybot/backups"
git fetch origin
git -C ../familybot-portal fetch origin
git switch --detach REVIEWED_CORE_SHA
git -C ../familybot-portal switch --detach REVIEWED_PORTAL_SHA
uv run --python 3.12 scripts/install_familybot.py \
  --portal-repo ../familybot-portal \
  --workspace "$HOME/.familybot" \
  --portal-runtime "$HOME/.familybot/runtime/familybot-portal" \
  --upgrade --writers-stopped
```

Substitute the next reviewed compatible pair, not the previous install's SHAs.
Keep the previous pair with the backup so rollback is reproducible. Detached
checkouts do not use `git pull`.

Every upgrade takes a verified full `pre-upgrade` SQLite backup before member,
calendar or schema changes, even if no migration is pending. Core and Portal
commit separately; the entire installer is not one transaction. If a later step
fails, keep writers stopped and use the pre-upgrade backup to undo earlier steps.
Portal validates its complete owned schema, history and integrity before commit
and again before API startup. A failed Portal migration does not mark versions
complete. Existing four/five-digit PINs remain valid; new installs require 6–8.

If Core schedules are enabled, redeploy them after the upgrade:

```bash
export FAMILYBOT_WORKSPACE="$HOME/.familybot"
export FAMILYBOT_FAMILY_CONFIG="$HOME/.familybot/config/family.local.json"
export FAMILYBOT_DEPLOY_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
bash scripts/deploy_core.sh --reload
```

## 12. Restore or roll back

Inspect database status:

```bash
uv run --python 3.12 scripts/manage_database.py status \
  --db "$HOME/.familybot/db/family.db"
```

Stop all database users before restoring a selected verified backup:

```bash
uv run --python 3.12 scripts/manage_database.py restore \
  --db "$HOME/.familybot/db/family.db" \
  --backup-root "$HOME/.familybot/backups" \
  --from-backup "/exact/path/to/backup/family.db" --writers-stopped
```

Restore verifies the source before replacing the database and creates a
pre-restore recovery backup of the current file. Recognized unversioned legacy
FamilyBot backups are supported without fabricating migration markers. A target
with SQLite WAL/SHM/journal sidecars is refused; never delete them to bypass this
guard. Then check out the matching Core and Portal commits and follow their
deployment instructions. Use the explicit upgrade path above only if choosing to
retry the new release, not while rolling back to the old release. Full
disaster-recovery order is in [REDEPLOY.md](REDEPLOY.md).

## 13. Troubleshooting

### The printed `.local` hostname does not open

```bash
launchctl print "gui/$(id -u)/ai.familybot.portal"
dns-sd -B _http._tcp local
curl -fsS http://127.0.0.1:8788/api/health
```

Check that the iPad is not on guest Wi-Fi and that the router permits mDNS
between household devices.

### An optional integration is unavailable

Keep the dashboard running. Validate only that integration's config and
credentials, then inspect the owner-only service log. Do not copy credentials
or private payloads into a public issue.

### Database migration stopped

Do not delete the database or edit the migration ledger. Preserve the error,
run `manage_database.py status`, identify the automatic backup, and follow the
restore command above.

### Full verification for contributors

Core:

```bash
cd "$HOME/FamilyBot/familybot-core"
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.txt requirements-dev.txt
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/ruff check scripts tests
```

Portal:

```bash
cd "$HOME/FamilyBot/familybot-portal"
npm ci
npm run lint
npm test
```

Automated clean-room tests prove empty initialization, chore approval, restart,
upgrade and migration recovery. They do not prove a household's mail account,
Spond account, provider contract, router, physical iPad or model entitlement.
