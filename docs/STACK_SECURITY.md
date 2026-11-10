# Stack maintenance and scheduled checks

FamilyBot's deterministic scheduler does not upgrade dependencies. Inventory,
advisory scanning, compatibility testing and deployment are separate operations.
An update being available does not prove it is safe for this household; a clean
scan does not prove that software is secure.

## Separate runtime contracts

The Portal currently requires Node 22.22.3–22.x. OpenClaw 2026.11.2 requires
Node 24.16+ on 24.x or 26.1+; its security guidance recommends at least
24.22.1/26.12.1. Use a separately installed, patched Node for the Gateway and
record its absolute path in the managed service. Do not globally switch the
Portal to a new Node major to satisfy OpenClaw. Verify both the shell CLI and
the actual service process. Sources: [OpenClaw runtime compatibility](https://docs.openclaw.ai/install/node-compatibility)
and [Node release inventory](https://nodejs.org/dist/index.json).

Core and Portal Python environments are separate too. Inventory their Python,
SQLite and OpenSSL versions, not just `/usr/bin/python3` or Homebrew's SQLite.
Python package audits do not cover those bundled native libraries. A Python
patch upgrade requires rebuilding the affected virtual environments from the
reviewed hash locks and testing before switching the service.
The auditor separately flags the known [SQLite WAL-reset risk](https://sqlite.org/wal.html#walresetbug)
below 3.51.3, recognizing the 3.44.6 and 3.50.7 backports. The race requires
concurrent connections writing/checkpointing a WAL database; FamilyBot's shared
database architecture makes a fixed runtime important. This one version check
is not a complete native-library vulnerability scan.

Keep the Codex executable independently discoverable/versioned. A path inside
a desktop application bundle can move on a desktop update. Never upgrade the
desktop app during an active operator session just to update FamilyBot's CLI.
Preserve model selection and provider authentication; prove each enabled agent
with a fictional no-delivery smoke test after a runtime change.

## Run a read-only audit

`scripts/stack_security_audit.py` is optional and uses only Python's standard
library. Its configuration is operator metadata, not a second family identity
configuration. Copy `ops/stack-audit.example.json` to the private workspace as
`config/stack-audit.local.json`, replace the absolute paths, remove tools you do
not use and set mode 0600. Do not include secrets. Configure `portal_repo` only
when auditing a source checkout with a reviewed `package-lock.json`.
Optionally set `codex_plugin_repo` to the active OpenClaw-managed npm project
directory containing the Codex plugin's `package-lock.json`. This adds a separate
dependency audit: OpenClaw's security audit checks configuration, not dependency
advisories. Reconfirm this path after plugin updates. A missing lock is unavailable,
not clean; do not generate a new production lock merely to silence the check.
The globally installed OpenClaw host may ship without a lock and is not completely
dependency-audited by this script. In particular, the 2026.11.2 host/plugin pins
Zod 4.6.5, affected by [GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5).
The fixed Zod release is 4.6.6. Do not use `npm audit fix --force` to replace a
managed plugin with an incompatible release; review an upstream fixed cohort or
an explicitly tested package override separately. Loopback/auth and bounded
inputs reduce exposure, but do not prove the vulnerability unreachable.

Install the auditor deliberately if needed, outside production environments:

```bash
uv venv --python 3.12 .audit-venv
uv pip sync --python .audit-venv/bin/python requirements-dev.txt
```

Point `pip_audit` at that environment's executable. It inspects the installed
Core/Portal environments via `--path`; it does not install or update their
packages. Missing/unconfigured tools are not evidence of clean coverage.

```bash
python3 scripts/stack_security_audit.py \
  --config /exact/workspace/config/stack-audit.local.json
```

The script records versions, stable release availability, bundled Python library
versions, installed Python package advisory counts, Portal **source-lock** npm
advisory counts and OpenClaw security counts. Node/Python updates are compared
within the installed major/minor to avoid recommending an incompatible major.
The source-lock check is not proof of the currently served web bundle. Confirm
its deployment receipt/source commit separately.

The private, atomically replaced `memory/stack-security-audit.json` includes a UTC
timestamp. Exit codes: 0 completed without findings; 1 findings need review;
2 at least one check was unavailable, invalid, timed out, or could not be saved.
Update availability alone is informational. An old timestamp or failed scheduled
run must not be read as a fresh clean result. OpenClaw's expected personal-agent
trust warnings remain visible; they are not silently suppressed.

Public npm/PyPI/GitHub/Node/Python endpoints receive package/version queries and
the host's IP, not family data. Reports contain allowlisted versions/counts only,
never raw CLI stderr, configuration, prompts, credentials or advisory descriptions.
No shell commands come from configuration. There are no model calls, household
database accesses, credential tests, Telegram sends, remediation or installations.
Underlying CLIs may refresh their own metadata caches; audit logs and reports
are the intended local writes, not a guarantee of a write-free filesystem.
Host OS updates, router exposure and unofficial provider contracts need separate
operator review. The scanner is not a security certification.

## Optional weekly launchd schedule

On macOS use launchd, not another Unix/OpenClaw cron owner. After a successful
manual run, generate a new definition (existing files are never overwritten):

```bash
python3 scripts/stack_security_audit.py \
  --config /exact/workspace/config/stack-audit.local.json \
  --write-launchagent "$HOME/Library/LaunchAgents/familybot.stack-audit.plist"
plutil -lint "$HOME/Library/LaunchAgents/familybot.stack-audit.plist"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/familybot.stack-audit.plist"
```

It runs Sundays at 12:15 in the Mac's local time, not immediately on load. It
uses the generating Python/script's absolute paths: keep those paths stable or
unload and regenerate the definition after moving the checkout. Review/change
the calendar interval before loading if desired. The job writes a short status
line to `logs/stack-audit.log`; protect and rotate that local log normally.
It does not join SRE's automatic recovery allowlist or generate repeated
Telegram alerts. Review the report during maintenance; this is not an attended
security incident response service.

Disable without deleting evidence:

```bash
launchctl bootout "gui/$(id -u)/familybot.stack-audit"
```

Remove only that known definition if retiring it. Reports/config remain private.

## Upgrade and rollback gate

1. Record actual CLI/service versions, executable paths, source refs and plugin
   pins. Inspect upstream release notes and required migration hops.
2. Back up OpenClaw state using its supported WAL-aware backup and verify it.
   Save the existing package/service definition separately. Keep backups private,
   encrypted at rest where available, and outside Git.
3. Pause only gateway-dependent schedules and their restart supervisor. Do not
   stop the independent dashboard or alter family.db for an OpenClaw update.
4. Run the supported updater using the chosen Node and owning installation.
   Pin the reviewed release. Bring official plugins into its compatible cohort;
   inspect widened capabilities before accepting them.
5. Treat a refused session migration as a stop condition. Preserve all recovery
   artifacts and use the documented recovery path. Never delete history, edit
   schema markers, or mix old configuration with newly migrated databases.
6. Validate config, channel health, minimal inference-agent tools, disabled
   legacy jobs, and exact no-delivery outputs. Resume the paused schedules only
   after those checks pass. Check the dashboard independently.
7. If forward repair cannot be verified, restore the matching backed-up package,
   configuration and OpenClaw state with its writers stopped. Do not restore the
   household database for an OpenClaw-only repair. Keep failed state for diagnosis.

See [OpenClaw updating](https://docs.openclaw.ai/install/updating),
[session recovery](https://docs.openclaw.ai/cli/doctor/sqlite-maintenance),
[rollback](https://docs.openclaw.ai/install/updating/rollback-and-recovery),
and the [FamilyBot setup audit](OPENCLAW_SETUP_AUDIT.md).
