# Installation readiness assessment

Initial assessment date: 2026-11-05. Scope: reviewed `dev` baselines of
`familybot-core` and `familybot-portal`, evaluated without private production
state or live household credentials.

## Follow-up review, 2026-11-06

The adversarial review of Core `e47d1fb` / Portal `8b849fa` concluded
**conditional GO for controlled dev testing, NO-GO for unaided public setup**.
The initial assessment below overstated restart/deployment coverage: reopening
a repository object is not restarting a process, and the old macOS CI used
`--no-deploy`. Those results are historical data-layer evidence only.

The coordinated readiness-fixes PRs address F1–F8 in
[the execution plan](READINESS_FIX_PLAN.md): explicit candidate setup refs,
real Mac hostname detection, clean-account launchd directories, consistent
workspace defaults, explicit grocery/AI consent, profile-aware truthful runtime
probes, actual API-process lifecycle tests and a disposable macOS managed-install
CI gate. No schema change or live household migration is included.

Local verification exercises fictional HTTP chore creation, completion,
parent authorization/approval, termination/restart, old-session rejection and
retained points after repeat installation. The PR review record contains exact
commands, final test totals and both commit SHAs. Managed macOS CI results must
be read from the final paired PR run, never inferred from these local tests.

The stopping point is **reviewed open PRs**, not merge or deployment. No existing
system is changed. Main release packaging, physical Mac/iPad LAN/Bonjour/touch
acceptance and live optional-provider verification remain separate owner gates.
The recommendation is a controlled test of the reviewed pair in the user's new
location; not an unconditional public release or a security certification.

## Before this work

Release readiness was **not acceptable for an independent household**.

| Priority | Verified defect | Consequence |
| --- | --- | --- |
| P0 | No authoritative empty-database initializer; setup required an owner-supplied `family.db` | A new household could not install |
| P0 | Core and Portal created/assumed tables independently without a shared version contract | Upgrades could drift or fail late |
| P1 | Weather, transport, OpenClaw and multiple schedules were described or deployed as baseline requirements | Dashboard-only use was not independent |
| P1 | Setup was a long manual assembly of config, PIN, database and deploy scripts | Failure-prone for a first-time operator |
| P2 | School dates and several time calculations were Oslo/owner shaped | Other municipalities and time-zone settings were unreliable |
| P2 | Recovery documented file copying but had no supported verified restore command | Unsafe rollback under pressure |
| P2 | CI did not exercise a checkout with no FamilyBot files or database | Unit success did not prove installation |
| P2 | Public docs described owner experiments and planned behavior as broadly operational | Fork users could not distinguish supported from experimental |

## Historical assessment after the initial installation PRs

The source is a **release candidate for the Dashboard profile**, subject to a
fresh physical Mac/iPad acceptance run before tagging. Connected and Agent
profiles are structurally installable but still require each household to prove
its own provider accounts and contracts.

| Acceptance area | Evidence | Status |
| --- | --- | --- |
| Empty initialization | Core migration v1 + Portal migration v2 from no file | Automated pass |
| Repeat install/data reopen | Installer run twice; repository reopened after chore approval | Historical data-layer pass, not process restart |
| Upgrade/data preservation | Legacy rows migrated with pre-migration backup | Automated pass |
| Migration failure | Transaction rollback and recovery backup | Automated pass |
| Restore | Source integrity check, pre-restore backup and data verification | Automated pass |
| Dashboard-only profile | No Core background jobs, no optional credentials, fictional household | Automated pass |
| Chore lifecycle | Repository create, complete, approve, reopen with points retained | Historical data-layer pass |
| Missing integrations | Weather/transport/provider absence returns isolated unavailable states | Automated pass |
| Invalid config | Validation stops before database creation | Automated pass |
| Fictional browser demo | Isolated API and Portal served the clean-room Nordlys data; screenshot captured | Local simulated pass, not hardware |
| macOS portability | Clean lifecycle and plist checks on `macos-15` CI | CI configured; requires PR run |
| Physical Mac mini/iPad | Bonjour, launchd, touch, rotation and Home Screen behavior | Not executed in this assessment |
| Live external accounts | IMAP, Spond, Telegram/model, Oda and HelloFresh | Not executed; household verification required |

## Security assurance and residual risk

The work improves safe defaults; it does not prove security.

- No default credential or real household dataset is needed or committed.
- Private directories/files are created as `0700`/`0600`.
- Migrations are versioned, checksummed, transactional and backed up before an
  existing schema changes.
- Optional integrations are off until explicitly configured, and failures are
  isolated from the dashboard.
- Browser responses remain curated and consequential provider actions remain
  allowlisted and confirmed.
- The default Portal is plain HTTP. A hostile LAN participant can observe data,
  PINs and session/provider login material. Origin checks are not client
  authentication. Do not expose it directly to the internet.
- Parent/child identity is a trusted-household appliance model, not individual
  user accounts. Oda/HelloFresh are intentionally available to every valid
  dashboard session.
- Member names and school profile fields can be updated by stable ID, but
  member retirement is not automated. Existing IDs must remain reserved so
  historical chores, plans and events are not silently deleted or reassigned.
- Spond is unofficial; HelloFresh is unsupported/reverse-engineered; Oda MCP is
  provider-controlled. Contract tests reduce accidental regressions but cannot
  guarantee future availability.
- Releases are not signed and local audit logs are not tamper-evident.

## Release sequencing after separate owner approval

If separately approved, merge Portal first **without deploying it**, then Core. This
keeps Core's post-merge cross-repository clean-install CI on one compatible
pair. Runtime rollout has the opposite data order: run the Core migration first,
then the Portal migration/deploy, because Portal schema v2 requires the Core v1
marker. After both PR gates pass, perform one clean install on a non-production
macOS account and one physical iPad dashboard/chore/approval/restart test. If
those pass, the Dashboard profile is suitable for a public release candidate.

Do not market Connected, Agent, Spond, Oda or HelloFresh as verified for a new
household until that household has completed the integration-specific smoke
test. Their failure must remain a degraded optional capability, never a failed
FamilyBot installation.
