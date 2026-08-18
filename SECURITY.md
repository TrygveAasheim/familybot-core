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
LAN is an accepted residual risk. Use network isolation, no port forwarding and
VPN access rather than exposing ports 3000/8788. TLS is required if the LAN is
not trusted.

## OWASP Top 10:2025 walkthrough

| Area | Current control | Residual risk / follow-up |
| --- | --- | --- |
| A01 Broken Access Control | Exact configured origin allowlist; child write token; parent token requires PIN; API write allowlist | Shared family device/session model is not individual identity; HTTP permits observation on a hostile LAN |
| A02 Security Misconfiguration | `validate_config.py`, owner-only files, explicit `--lan`, no cloud database, no-store/security API headers | LaunchAgent schedules remain partly host-specific; firewall/router configuration is operator-owned |
| A03 Software Supply Chain Failures | npm lockfile, pinned Python dependencies, test/build/audit release gate | No signed releases or hash-locked Python artifact set; unofficial Spond client is higher risk |
| A04 Cryptographic Failures | Secrets excluded from Git and stored owner-only; tokens generated with `secrets` | Local HTTP does not encrypt browser traffic; backup encryption is external to the app |
| A05 Injection | Parameterized SQLite statements, bounded JSON, strict enums/dates/IDs, no raw browser-to-shell path | PDF/email parsers still process attacker-controlled content and require continued fuzz/fixture coverage |
| A06 Insecure Design | Local-first trust boundaries, curated API, inference outside durability, backups before writes | Children intentionally need no login; any trusted dashboard device can register a child completion |
| A07 Authentication Failures | Parent PIN comparison, random in-memory parent token, five-attempt/five-minute rate limit | PIN is shared and server-restart resets the in-memory throttle; use 6–8 random digits |
| A08 Software or Data Integrity Failures | Idempotency keys, SQLite constraints, atomic writes, integrity checks, reviewed `main` deployment | Audit log is local and not tamper-evident; no signed update channel |
| A09 Security Logging and Alerting Failures | Owner-only audit log, health snapshot, job freshness, launchd logs | No external security alert sink; host loss also loses unshipped logs |
| A10 Mishandling Exceptional Conditions | Bounded timeouts/payloads, generic client errors, durable retry/outbox, supervisor restarts | External API schema changes can degrade integrations until adapters are updated |

Reference baselines: [OWASP Top 10:2025](https://owasp.org/Top10/2025/),
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/),
[Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
and [OWASP IoT Security Testing Guide](https://owasp.org/owasp-istg/).

## Data minimization

The portal returns selected columns only. It excludes raw email text, sender
addresses, Telegram IDs, Spond `raw_json`, tokens, attachments and filesystem
paths. Runtime data, backups, config, PIN and audit logs are Git-ignored.

Review new fields before adding them to `/api/dashboard`. A value being present
in SQLite does not make it suitable for a child's screen or browser response.

## Smart Home boundary

Smart Home remains an optional add-on behind Home Assistant. Vendor credentials
stay in Home Assistant or a separate owner-only store. The FamilyBot adapter
allowlists entities and actions; the browser cannot issue arbitrary Home
Assistant service calls. Camera access and consequential appliance/climate
commands require parent authorization and audit. Every device reports whether
its state is Local, Cloud, Experimental, Stale or Offline.

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
to exact versions and resolve duplicate install metadata before the next
OpenClaw upgrade.

## Security release gate

Before promotion:

```bash
python3 scripts/validate_docs.py
python3 scripts/validate_config.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile scripts/*.py
bash -n scripts/*.sh

cd ../familybot-portal
npm ci
npm run lint
npm test
npm audit
python3 tests/acceptance.py
```

Also check staged files with `git diff --cached --check` and inspect names of
all staged files. Never run a secret scanner in a way that prints matched
values into shared logs.

## Reporting and rotation

For a suspected leak: stop affected jobs, revoke the credential at its issuer,
replace the local secret, restart the relevant service, verify capability and
review Git history. Rewriting history does not revoke a credential.
