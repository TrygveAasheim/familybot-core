# Security posture

This is a practical threat model and OWASP review, not a certification. The
current target is an ASVS Level 1-inspired baseline for a private home-LAN
application, with stronger controls around credentials and parent writes.

## Assets and threat model

Protected assets include children's identities, school plans, schedules,
locations, email-derived facts, Spond content, Telegram identifiers, household
tasks, camera images, appliance state, tokens and credentials. Expected threats
are accidental Git disclosure,
malicious email/PDF content, an untrusted device on the LAN, PIN guessing,
dependency compromise, failed jobs and loss of the Mac mini.

The service is **not safe for direct internet exposure**. HTTP on a trusted home
LAN is an accepted residual risk, not encryption. A device able to observe or
modify LAN traffic can capture dashboard data, the in-memory session token, the
parent PIN during login and any first-use provider password. Browser Origin
checks reduce cross-site misuse but do not authenticate a non-browser client,
which can forge an Origin header. Use an isolated household LAN, no port
forwarding and authenticated VPN access. Add a reviewed TLS reverse proxy before
using guest/shared Wi-Fi or any network whose clients are not mutually trusted.

## OWASP Top 10:2025 walkthrough

| Area | Current control | Residual risk / follow-up |
| --- | --- | --- |
| A01 Broken Access Control | Exact configured origin allowlist; random local token; parent token requires a rate-limited PIN; API action allowlists | Shared family device/session model is not individual identity; Oda/HelloFresh actions intentionally follow the trusted-household policy rather than the parent PIN |
| A02 Security Misconfiguration | Profile-aware installer, `validate_config.py`, owner-only files, explicit LAN binding, no cloud database, no-store/security API headers | Firewall, router isolation, VPN and any TLS termination remain operator-owned |
| A03 Software Supply Chain Failures | npm lockfile, hash-locked Python dependencies, pinned CI actions, test/build/audit release gate | No signed release/update channel; unofficial Spond and unsupported HelloFresh contracts are higher risk |
| A04 Cryptographic Failures | Secrets excluded from Git and stored owner-only; tokens generated with `secrets` | Local HTTP does not encrypt browser traffic; backup encryption is external to the app |
| A05 Injection | Parameterized SQLite statements, bounded JSON, strict enums/dates/IDs, no raw browser-to-shell path | PDF/email parsers still process attacker-controlled content and require continued fuzz/fixture coverage |
| A06 Insecure Design | Local-first trust boundaries, curated API, inference outside durability, backups before writes | Children intentionally need no login; any trusted dashboard device can register a child completion |
| A07 Authentication Failures | Parent PIN comparison, random in-memory parent token, five-attempt/five-minute rate limit | PIN is shared, token lasts until process restart/re-login and restart resets the throttle; use 6–8 random digits and a trusted LAN |
| A08 Software or Data Integrity Failures | Idempotency keys, SQLite constraints, atomic writes, integrity checks, reviewed source-pair deployment | Audit log is local and not tamper-evident; no signed update channel |
| A09 Security Logging and Alerting Failures | Owner-only audit log, health snapshot, schedule-aware job freshness, bounded SRE action log, launchd logs | No external security alert sink; host loss also loses unshipped logs |
| A10 Mishandling Exceptional Conditions | Bounded timeouts/payloads, generic client errors, durable retry/outbox, cooldown-limited supervisor recovery | External API schema changes can degrade integrations until adapters are updated; briefing replay remains manual to avoid duplicates |

Reference baselines: [OWASP Top 10:2025](https://owasp.org/Top10/2025/),
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/),
[Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
and [OWASP IoT Security Testing Guide](https://owasp.org/owasp-istg/).

## Data minimization

The portal returns selected columns only. It excludes raw email text, sender
addresses, Telegram IDs, Spond `raw_json`, tokens and filesystem paths. Registered
original Ukeplan PDFs are an explicit attachment exception: a child/plan-bound,
session/Origin-protected route serves only confined `db/attachments` PDFs.
School-provided personal information printed in those documents is visible to
trusted LAN sessions, not restricted by individual child identity. Unrelated
attachments remain private. The local passive viewer does not execute PDF actions
or upload documents. Plain-HTTP LAN interception remains a risk; see Portal's
`docs/DATA_BOUNDARY.md`. Runtime data, backups, config, PIN and audit logs are Git-ignored.

Review new fields before adding them to `/api/dashboard`. A value being present
in SQLite does not make it suitable for a child's screen or browser response.

## Installation, database and backup safety

The installer creates private directories as `0700` and config, PIN, database
and backups as `0600`. It rejects credential-shaped fields in the family JSON.
Core and Portal migrations use a version/checksum ledger and transactions. A
pending migration on an existing database first creates and verifies a SQLite
backup; a failure rolls back and does not mark the version complete. Restore
verifies the selected source before replacement and creates a pre-restore copy.

Explicit upgrades additionally back up the entire database before member or
calendar synchronization even when no migration is pending. Portal validates
owned columns, migration history, integrity and foreign keys before committing
markers and before API startup. These checks are not a security proof or a
cross-component atomic transaction. Keep all database users stopped through
upgrade/recovery; the acknowledgement flag does not enforce process exclusion.
Restore rejects target SQLite sidecars and validates recognized legacy backups
without adding new markers. Follow [REDEPLOY.md](REDEPLOY.md), including the
separate private configuration/credentials backup. Existing 4–5 digit parent
PINs are preserved for compatibility but remain weaker than the new 6–8 digit
recommendation; this does not strengthen plain-HTTP LAN confidentiality.

These controls do not encrypt backups. The operator must place backup copies in
an encrypted store and protect the Mac account and FileVault. A local user with
access to the service account can read household data and credentials.

## External processing and consent

The Dashboard profile sends no household data to an LLM by default and needs no
AI account. Independently enabling `portal.features.oda_ai` consents to bounded
dinner requests/preferences being processed externally and requires its isolated
OpenClaw agent; Oda without AI remains usable. Enabling the Agent profile is
explicit consent to send bounded briefing
or Ukeplan context to the configured model provider. Tool-free inference agents
receive curated task data, not credentials, raw mailbox access or browser/tool
authority. External email, PDF and provider content is treated as untrusted data
and cannot select tools.

MET/Entur requests disclose configured coordinates or stops; IMAP/Spond expose
the account-selected source data; Telegram carries the generated message; Oda
and HelloFresh receive only their bounded account operations. See the Portal's
`docs/DATA_BOUNDARY.md` before enabling grocery integrations.

## Planned Smart Home boundary (not implemented)

Smart Home is a proposed optional add-on behind Home Assistant. Its future
adapter must keep vendor credentials in Home Assistant or a separate owner-only
store, allowlist entities/actions, and forbid arbitrary browser service calls.
Camera access and consequential appliance/climate commands must require parent
authorization and audit. Every device must report whether its state is Local,
Cloud, Experimental, Stale or Offline. These are implementation requirements,
not evidence of existing controls or connected devices.

The Mac mini must not expose Home Assistant, portal or camera ports directly to
the internet. True cabin-local control requires a cabin-side node and reviewed
VPN rather than a public port forward. See [specs/SMART_HOME.md](specs/SMART_HOME.md).

## OpenClaw operator boundary

The current Telegram/OpenClaw gateway follows a personal-assistant trust model:
configured parents are trusted operators, not hostile tenants. Do not add
children, public groups or untrusted users to a context that exposes runtime or
filesystem tools. If mutually untrusted users are ever added, use separate
gateway/OS-user boundaries or enable full sandboxing, workspace-only file access
and a minimal per-channel tool allowlist first.

The OpenClaw control UI is intentionally loopback-only. A missing
`trustedProxies` value is therefore expected; configure it only if a reviewed
reverse proxy is actually introduced. Pin separately installed OpenClaw plugins
to exact versions, add only trusted IDs to `plugins.allow`, and resolve duplicate
install metadata before the next OpenClaw upgrade.

## Security release gate

The optional [stack audit](docs/STACK_SECURITY.md) records installed versions and
advisory counts on a weekly opt-in schedule. Unknown, timed-out and partial
results remain unavailable, never clean. It performs no automatic upgrades,
credential checks or remediation. Review bundled SQLite/OpenSSL and macOS
separately; package-audit success does not cover those boundaries.

Before promotion:

```bash
python3 scripts/validate_docs.py
python3 scripts/validate_config.py
ruff check scripts tests
bandit -q -r scripts -x '*/test_*.py' --severity-level medium --confidence-level medium
pip-audit -r requirements.txt --disable-pip
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh

cd ../familybot-portal
npm ci
npm run lint
npm test
npm audit
python3 tests/acceptance.py --workspace /exact/test/workspace --host TEST-MAC.local
```

Deployment also reconciles the dedicated `familybot-briefing` and
`familybot-ukeplan` inference agents. Their tools, skills and elevated access
remain disabled so email and PDF content cannot trigger general OpenClaw tools.

Also check staged files with `git diff --cached --check` and inspect names of
all staged files. Never run a secret scanner in a way that prints matched
values into shared logs.

## Reporting and rotation

For a suspected leak: stop affected jobs, revoke the credential at its issuer,
replace the local secret, restart the relevant service, verify capability and
review Git history. Rewriting history does not revoke a credential.
