# Install FamilyBot on a Mac

This is the canonical first-time setup guide for both public repositories. It
is written for a household operator who is comfortable copying commands but is
not expected to know Python, Node.js, `launchd` or OpenClaw.

FamilyBot has two sibling repositories:

```text
familybot-core/       email, PDFs, Spond, schedules, briefings and durable data
familybot-portal/     iPad dashboard, chores, rewards, Oda and HelloFresh
```

Allow an hour for the software installation and configuration. Account consent,
mailbox setup and household customization can take longer.

> **Current clean-install limitation:** this release can restore and migrate a
> supported `family.db`, but it cannot create every historical Core table from
> an empty file. A first-time household therefore needs a supported starter
> database or a reviewed migration supplied by the project owner. Do not create
> tables by copying SQL from tests. The setup checker identifies this clearly
> before deployment.

## 1. Choose the footprint you want

You can start small and add integrations later.

| Footprint | What works | Additional software/accounts |
| --- | --- | --- |
| Dashboard | Existing family data, chores, rewards, weather, Entur, Oda and optionally HelloFresh | Core + Portal, Node.js, Python, `uv`, SQLite; Oda/HelloFresh accounts only when enabled |
| Full family assistant | School mail, interpreted Ukeplan, natural-language briefings, Telegram delivery and monitoring | Small OpenClaw gateway/CLI footprint, one OpenAI-authenticated agent and one Telegram bot |
| Spond add-on | Spond activities in the dashboard and briefings | Dedicated Spond credentials; the client is unofficial |

OpenClaw is not the database, web server or scheduler. For the full footprint it
provides only:

1. the loopback-only local gateway and CLI;
2. one `main` agent authenticated to OpenAI;
3. the Telegram channel; and
4. an optional isolated, tool-free `familybot-oda-dinner` agent created by the
   Portal deploy script.

No OpenClaw browser UI, public gateway, extra skill pack, web-search provider or
third-party plugin is required. Without OpenClaw, deterministic ingestion and
the LAN dashboard remain independent, but Telegram, LLM Ukeplan interpretation
and model-written briefing text are unavailable. Oda falls back to direct
recipe search.

The bundled Core schedule is the full-assistant profile. Dashboard-only users
deploy Portal and skip the Core LaunchAgents. Individual deterministic scripts
can still be run for development, but a selectively scheduled mail-only Core
service is not a supported appliance profile in this release.

## 2. What you need before starting

- An always-on Mac. Apple Silicon is the tested host; Intel macOS should work
  because executable paths are discovered at deployment, but it is not tested
  in CI.
- A normal, dedicated non-admin macOS account when practical.
- An iPad or browser on the same trusted home network.
- A supported `family.db` backup or starter database.
- For school mail: a dedicated mailbox or app password with IMAP access.
- For Telegram: a bot token created through Telegram and the parent chat IDs.
- For inference: OpenAI access through an OpenClaw-supported login flow.
- No router port forwarding for ports `3000` or `8788`.

The service is intentionally LAN-only. Telegram, weather, transport, email,
Spond, Oda, HelloFresh and the model provider are the expected outbound
connections.

## 3. Install the host software

### Tested baseline

| Software | Tested/required baseline | Why it is present |
| --- | --- | --- |
| macOS Command Line Tools | Current macOS release | Git and standard build utilities |
| Homebrew | Current stable | Installs the remaining command-line tools |
| Node.js | `22.22.3` through the latest `22.x` | Portal build/runtime and OpenClaw |
| Python | `3.12` in isolated `uv` environments | Core and Portal services |
| `uv` | Current stable | Reproducible Python environments |
| SQLite CLI/library | Current macOS/Homebrew release | Durable local database and integrity checks |
| Himalaya | `1.2.0+` | IMAP email ingestion |
| OpenClaw | Tested with `2026.7.1-2` | Optional full assistant/Telegram footprint |
| Git, `curl`, `rsync`, `dns-sd`, `launchctl` | Supplied by macOS/Command Line Tools | Source, APIs, deployment and Bonjour |

Install Apple's Command Line Tools first:

```bash
xcode-select --install
```

If Homebrew is not installed, use the installation command from
[brew.sh](https://brew.sh/). Then install the tested toolchain:

```bash
brew install node@22 uv sqlite himalaya
echo 'export PATH="$(brew --prefix node@22)/bin:$PATH"' >> "$HOME/.zprofile"
export PATH="$(brew --prefix node@22)/bin:$PATH"
uv python install 3.12
```

For the full assistant footprint, install the tested OpenClaw release from npm:

```bash
npm install --global openclaw@2026.7.1-2
```

Confirm that the shell sees the expected tools:

```bash
node --version
npm --version
uv --version
himalaya --version
sqlite3 --version
openclaw --version   # full assistant footprint only
```

If `node --version` is older than `22.22.3`, close and reopen Terminal and
check the PATH line in `$HOME/.zprofile`.

## 4. Clone the repositories together

Choose a private working directory outside any cloud-synchronized folder:

```bash
mkdir -p "$HOME/FamilyBot"
cd "$HOME/FamilyBot"
git clone https://github.com/TrygveAasheim/familybot-core.git
git clone https://github.com/TrygveAasheim/familybot-portal.git
```

The resulting directory must look like this:

```text
$HOME/FamilyBot/
  familybot-core/
  familybot-portal/
```

Use `main` for the public stable baseline. The project owner deploys active
development from `dev`; a fork may use its own release workflow.

## 5. Create isolated development environments

Install Core's two pinned runtime packages:

```bash
cd "$HOME/FamilyBot/familybot-core"
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.txt
```

Install Portal's Node.js dependencies and Python runtime/quality tools:

```bash
cd "$HOME/FamilyBot/familybot-portal"
npm ci
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.txt
uv pip install --python .venv/bin/python --requirement requirements-dev.txt
source .venv/bin/activate
```

Run the privacy-safe source readiness check. It prints executable paths and
pass/fail status, never credentials or household values:

```bash
cd "$HOME/FamilyBot/familybot-core"
.venv/bin/python scripts/check_setup.py --mode source
```

OpenClaw and Himalaya are warnings in source mode because the dashboard-only
footprint can omit them. They become required in the full runtime check.

## 6. Configure the minimal OpenClaw footprint

Skip this section for a dashboard-only installation.

Run OpenClaw's interactive local onboarding. Choose an OpenAI login supported
by your account, keep the gateway bound to loopback, install its launchd daemon,
and use the default `main` agent workspace:

```bash
openclaw onboard --flow quickstart --mode local --install-daemon \
  --workspace "$HOME/.openclaw/workspace"
```

You do not need to enable optional skills, web search, external plugins, a LAN
gateway or a public control UI. Add Telegram through the guided channel flow:

```bash
openclaw channels add --channel telegram
```

Do not put the Telegram token or OpenAI credential in either Git repository or
in `family.local.json`. OpenClaw owns those credentials.

Verify only capabilities, not secret values:

```bash
openclaw gateway health
openclaw models status
openclaw channels status --probe
openclaw agent --agent main --message "Reply exactly: MODEL_OK" --json
```

The last command uses a small amount of model capacity. A successful catalog
listing alone does not prove that the authenticated account can run the model.

## 7. Configure school email with Himalaya

Skip this section if school email ingestion is not wanted.

Use a dedicated mailbox or an app password rather than a primary account
password. The account name must match `integrations.email.account` in the
FamilyBot configuration:

```bash
himalaya account configure familybot
himalaya account doctor familybot
himalaya folder list --output json
```

Himalaya normally stores configuration under
`$HOME/.config/himalaya/config.toml` and uses the secret mechanism selected in
its wizard. Never copy that file into either repository.

## 8. Create the private household configuration

Core owns the only public template. Copy it outside Git:

```bash
cd "$HOME/FamilyBot/familybot-core"
install -d -m 700 "$HOME/.openclaw/workspace/config"
install -m 600 config/family.example.json \
  "$HOME/.openclaw/workspace/config/family.local.json"
${EDITOR:-nano} "$HOME/.openclaw/workspace/config/family.local.json"
.venv/bin/python scripts/validate_config.py
```

Replace every placeholder. Configure:

- stable IDs, names and roles for family members;
- parent Telegram targets only when Telegram is enabled;
- the Himalaya account and forwarding addresses when email is enabled;
- Spond groups only when Spond is enabled;
- exact Entur stop/quay IDs and the relevant station corridor;
- MET coordinates and an identifiable contact User-Agent; and
- exact Portal origins that the household's iPad will use.

Read [CONFIGURATION.md](CONFIGURATION.md) for every field. The file contains
private household metadata, but no passwords, tokens or API keys.

## 9. Restore the supported database

Stop here if you do not have a supported starter or backup database. Empty
database creation is the remaining clean-install blocker.

Restore it with owner-only permissions:

```bash
install -d -m 700 "$HOME/.openclaw/workspace/db"
install -m 600 /path/to/your/family.db \
  "$HOME/.openclaw/workspace/db/family.db"
sqlite3 "$HOME/.openclaw/workspace/db/family.db" \
  "PRAGMA integrity_check; PRAGMA foreign_key_check;"
```

The first result must be `ok`; the foreign-key query should return no rows.
Never commit the database. Git restores source, not household state.

## 10. Create the Portal parent PIN

Use six to eight random digits. This protects parent actions on the trusted LAN;
it is not an internet-grade account system.

```bash
cd "$HOME/FamilyBot/familybot-portal"
install -d -m 700 runtime
read -r -s -p "Parent PIN: " FAMILYBOT_PARENT_PIN
printf '\n'
printf '%s\n' "$FAMILYBOT_PARENT_PIN" > runtime/parent-pin.txt
unset FAMILYBOT_PARENT_PIN
chmod 600 runtime/parent-pin.txt
```

## 11. Add optional credentials

Follow [CREDENTIALS.md](CREDENTIALS.md). In particular:

- Spond credentials go in
  `$HOME/.openclaw/workspace/secrets.env` with mode `0600`;
- Oda uses same-window OAuth from the Portal and stores renewable tokens in an
  owner-only file outside Git;
- HelloFresh is disabled by default and stores only renewable provider tokens,
  never the password; and
- the Portal PIN remains in the ignored Portal runtime directory.

## 12. Run all checks before installing services

Core:

```bash
cd "$HOME/FamilyBot/familybot-core"
.venv/bin/python scripts/validate_docs.py
.venv/bin/python scripts/validate_config.py
.venv/bin/python scripts/validate_launchd.py
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m py_compile scripts/*.py
bash -n scripts/*.sh
```

Portal:

```bash
cd "$HOME/FamilyBot/familybot-portal"
source .venv/bin/activate
npm run docs:check
npm run lint
npm test
npm run preflight
```

Then run the full readiness check. It suppresses command output from OpenClaw
and Himalaya so diagnostics cannot accidentally expose mailbox or provider
details:

```bash
cd "$HOME/FamilyBot/familybot-core"
.venv/bin/python scripts/check_setup.py --mode runtime
```

For a dashboard-only footprint, select its capability profile:

```bash
# Existing-data dashboard without school mail or Telegram/AI
.venv/bin/python scripts/check_setup.py --mode runtime --profile dashboard
```

The `mail` profile is also available to contributors testing the deterministic
ingestion component in isolation. Resolve every `FAIL`. A `WARN` is an
explicitly optional integration.

## 13. Deploy the services

The public stable branch is `main`; the project owner's active appliance uses
reviewed `dev` deployments. The deploy scripts default to `dev` for that owner
workflow, while a fork can explicitly name its reviewed release branch with
`FAMILYBOT_DEPLOY_BRANCH`.

Dashboard-only users skip this Core service step and deploy Portal below. For
the full assistant, deploy Core first on the project owner's `dev` branch:

```bash
cd "$HOME/FamilyBot/familybot-core"
bash scripts/deploy_core.sh --reload
```

For a new fork deploying its reviewed `main` branch instead:

```bash
FAMILYBOT_DEPLOY_BRANCH=main bash scripts/deploy_core.sh --reload
```

Core deployment creates an isolated Python 3.12 runtime under
`$HOME/.openclaw/workspace/runtime/core`, copies reviewed scripts, installs all
nine base LaunchAgents, installs the tenth Spond job only when at least one
Spond group is configured, and reloads the installed jobs when requested.

Deploy Portal second:

```bash
cd "$HOME/FamilyBot/familybot-portal"
bash scripts/deploy-local.sh
.venv/bin/python tests/acceptance.py
```

For a reviewed `main` branch in a fork, use:

```bash
FAMILYBOT_DEPLOY_BRANCH=main bash scripts/deploy-local.sh
.venv/bin/python tests/acceptance.py
```

Portal deployment records the exact Node executable selected during setup,
creates its isolated Python 3.12 runtime and installs the web/API and optional
HelloFresh image-prefetch LaunchAgents.

## 14. Open the dashboard and verify one real flow

From the Mac, open:

```text
http://familie.local:3000/
```

Then test from the iPad on the same LAN. Verify, in this order:

1. the home page loads and the clock advances;
2. weather and Entur show either current data or an honest unavailable state;
3. each child page opens;
4. one chore completion and parent decision persist after refresh;
5. one school email/PDF becomes the correct child's Ukeplan;
6. one Telegram test reaches each configured parent; and
7. `python3 tests/acceptance.py` reports every critical Portal criterion passed.

Only after these pass should you add the dashboard to the iPad Home Screen.

## Troubleshooting map

| Symptom | Start here |
| --- | --- |
| A command is missing or the wrong version | `.venv/bin/python scripts/check_setup.py --mode source` |
| Configuration is rejected | [CONFIGURATION.md](CONFIGURATION.md) and `scripts/validate_config.py` |
| OpenClaw/model/Telegram fails | `openclaw doctor`, `openclaw gateway health`, `openclaw models status`, `openclaw channels status --probe` |
| Mail fails | `himalaya account doctor familybot` and [CREDENTIALS.md](CREDENTIALS.md) |
| A scheduled job is absent | [docs/SCHEDULES.md](docs/SCHEDULES.md) and `scripts/deploy_core.sh --reload` |
| Portal preflight fails | `npm run preflight`; confirm sibling Core, config, database and PIN |
| `familie.local` does not resolve | Check `ai.familybot.portal`, `dns-sd` and the iPad's LAN/guest-network placement |
| Restoring after a host failure | [REDEPLOY.md](REDEPLOY.md) |

## What every fork must customize

- Family members, schools, teacher/sender rules and forwarding conventions.
- Entur stop/quay IDs, station corridor and MET coordinates.
- The school calendar: the included Oslo seed is not a universal Norwegian
  calendar and must be kept current.
- Spond groups and whether the unofficial adapter is acceptable.
- Portal origins, Bonjour name, parent PIN and optional grocery provider flags.
- Branch/deployment policy if it differs from the owner's `dev` workflow.

Do not describe Smart Home as installed: it remains a separately reviewed plan
in [specs/SMART_HOME.md](specs/SMART_HOME.md).
