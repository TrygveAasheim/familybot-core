# New-household readiness: execution and review plan

Baseline: Core `e47d1fb`, Portal `8b849fa` (reviewed development branches).
Scope: two coordinated `codex/readiness-review-fixes` PRs targeting `dev`.
Stop at reviewed, open PRs. No merge, deployment, production state inspection,
account access, credential use or promotion to `main` is authorized by this work.

## Findings and exact implementation requirements

| ID | Defect | Owning implementation | Acceptance and regression evidence |
| --- | --- | --- | --- |
| F1 | Setup clones main where installer is absent | Both READMEs, Core GETTING_STARTED, Portal docs validator | Candidate instructions select the same explicit branch in both repos; final PR handoff records both full SHAs; no claim main is ready |
| F2 | `familie.local` is assumed rather than registered | Core installer; Portal deployment output | New wizard/demo uses macOS LocalHostName, explicit hostname override is validated, existing config is preserved; correct Origin/session/dashboard and hostname resolution are checked; unrelated HTTP 200 is rejected |
| F3 | Clean account lacks LaunchAgents directory | Portal deploy-local | Create missing per-user launch/log directories before plist installation; reject unavailable GUI launchd domain before stopping services; isolated tests never touch the owner's jobs |
| F4 | Clean-install CI tests data only | Core process lifecycle tests and macOS workflow | Actual API subprocess, authentication, chore creation/completion/approval, restart, old-session rejection, retained points, repeat installer; macOS builds and exercises managed installation on disposable runner |
| F5 | Acceptance assumes transport, two children, 30-point rewards and old browser results | Portal acceptance runner/tests/docs | Explicit target required, no import-time runtime reads, zero/one/three children and custom reward targets supported; disabled providers not contacted; `pass/fail/not_applicable/not_run` separated; historical browser JSON never counted |
| F6 | Tools silently use legacy workspace | Core/Portal Python and shell entry points | CLI path overrides environment; FAMILYBOT_WORKSPACE precedes OPENCLAW_WORKSPACE, then `.familybot`; no automatic legacy discovery; explicit legacy paths preserved; installer rejects conflicting ambient config/database paths |
| F7 | Markdown disagrees with code and optional consent | Both docs/contracts, Portal feature defaults | Grocery flags opt in explicitly; Oda AI separately consents to external processing; guarded HelloFresh writes accurately documented; session lifetime and schema validation claims match implementation |
| F8 | Hardware/provider validation absent | Readiness assessment and manual checklist | Exact commit pair and evidence class recorded; iPad, LAN Bonjour and provider tests remain unverified until actually performed |

## Stage 1: installation correctness

1. Work in separate source worktrees; record clean baseline and full SHAs.
2. Normalize workspace resolution without reading or migrating legacy state.
   Keep explicit overrides working. Add default/legacy/custom-path tests.
3. Detect `scutil --get LocalHostName` for new macOS wizard/demo installs.
   Never rename the Mac. Preserve supplied/existing config; offer a validated
   hostname override only for new configuration. Add missing exact web origin.
4. Verify API identity, a local session, authenticated dashboard and web content,
   not just successful HTTP status. Verify the configured hostname locally and
   report LAN/iPad verification separately.
5. Create deployment directories safely. Check launchd domain before mutation.
   Support isolated generated labels/directories for disposable CI only.
6. Require explicit grocery and AI flags; document the upgrade action for
   older files that omitted those flags. Do not enable anything automatically.

## Stage 2: evidence that exercises the installed application

1. Replace acceptance's implicit private targets with required workspace and
   explicit host; make network probes read-only and provider checks opt-in.
2. Separate automated probes from full release criteria. A passing HTTP probe
   must never satisfy a physical touch/layout, provider or restart criterion.
   Unmeasured criteria stay `not_run`; disabled capabilities `not_applicable`.
3. Initialize fictional households through production migrations, not fixture
   SQL. Start real API subprocesses on isolated loopback ports. Perform parent
   login, create, complete, deny child approval, approve, terminate/restart,
   verify token invalidation and preserved progress, then reinstall and verify.
4. Preserve existing upgrade/migration failure/restore tests; extend invalid
   configuration, hostname, missing credentials and wrong-service tests.
5. macOS CI installs the documented Node/Python/uv baseline, builds the web app,
   and runs managed installation with unique jobs and temporary private state.
   Lack of a GUI launchd domain is a visible failure, not successful deployment.
   Always stop only test-owned jobs. No such deployment runs on the owner's Mac.
   Hosted runners use an explicit localhost configuration because their `.local`
   name may not resolve. This tests managed processes, not household LAN/mDNS;
   production hostname verification remains unchanged and the physical gate stays open.

## Stage 3: documentation and review

Audit every tracked Markdown file. Update active contracts and commands in the
same behavioral commit; preserve historical records but label their evidence
as historical. Reconcile AGENTS, CHANGE_PROTOCOL, BRANCHES, setup, recovery,
configuration, security, grocery, acceptance and feature/readiness guides.
Core GETTING_STARTED remains the canonical new-user guide. Do not require an
integration account for Dashboard or describe unsupported providers as proven.

CI toolchain note: install the pinned uv runner separately from the hash-locked
Python requirements; mixing an unhashed command-line package into that lock
correctly fails pip's hash verification and never reaches installation tests.

Run Core docs/config/unit/compile/shell/Ruff/Bandit/dependency checks and Portal
docs/lint/API/build/render/security checks; record exact commands and scopes.
Then run two independent reviews of the final paired changes: affirmative
first-time-user journey and skeptical security/recovery review. Resolve
actionable blockers with regression tests, rerun affected/full checks, and
request re-review of changed code. Do not equate agent review with owner approval.

## PR sequencing and stop condition

Use coherent correctness, acceptance/CI and documentation commits in each PR.
Portal is the first potential merge because Core's new integration checks need
the corrected Portal. Test Core against the exact Portal head; record both
SHAs in both PRs. Matching branch CI must report its selected SHA, not imply an
old dev fallback tested the candidate. After a later owner-authorized merge,
rerun Core CI against merged Portal dev before merging Core. Neither merge is
part of this task. Main promotion is a separate paired release after acceptance.

Stop with open reviewed PRs, findings/resolutions, test evidence, residual risks
and exact pinned-checkout test commands. A fresh local test may be recommended;
an unaided public release is not recommended until the release refs contain the
installer and the physical Mac/iPad gate has evidence.

## Rollback and manual gate

No schema change is planned. Reverting the two PRs restores source behavior;
never restore a database merely to undo documentation or default-path changes.
An installer execution elsewhere may create config/runtime/plists: retain its
private state, stop only its generated jobs, select the recorded prior source
pair and redeploy explicitly. Schema rollback follows REDEPLOY's verified
backup/restore procedure, never file-copying a running SQLite database.

On the user's separate test Mac: install with fictional data, use the printed
URL from an iPad on the same LAN, add a Home Screen shortcut, test portrait,
landscape, 200% text/zoom, tap targets, parent approval, relaunch/reboot and
retained points. Record macOS/iPadOS versions, UTC timestamp, both commit SHAs
and outcomes without PINs or personal data. Test optional providers only after
explicitly enabling them and supplying credentials there. Plain HTTP and shared
LAN sessions remain documented risks, not solved by these PRs.
