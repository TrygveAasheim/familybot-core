# Change protocol

Use this protocol for every behavioural change. The amount of evidence scales
with risk, but no production change skips classification, tests or rollback
thinking.

This is also the shared change-record standard for every bug fix, new feature
and improvement. A change is not complete until its intent, acceptance,
verification and operational handoff are recorded in the pull request, issue
or commit description. Forks may use a different hosting workflow, but should
keep this record structure.

## 1. Classify before editing

| Class | Examples | Minimum discipline |
| --- | --- | --- |
| Core-critical | ingestion, routing, parser attribution, SQLite schema, outbox, schedules, health | backup/copy state, focused fixtures, full core suite, failure-path test, rollback plan |
| Bounded adapter | Spond, MET, Entur, mail command wrapper | recorded/fixture response, timeout/error test, stale-state behaviour, full core suite |
| Curated API/data boundary | portal response or mutation, new database read | allowlist/privacy review, authorization negatives, API tests, portal acceptance |
| Add-on | Smart Home provider, camera, menu source, optional dashboard page | isolated provider contract, disabled-by-default config, no core dependency, graceful unavailable state |
| Documentation only | prose, links and runbooks | documentation validator, command/path spot-check, `git diff --check` |

If a feature seems to require an add-on to write the email ledger or delivery
outbox, stop and redesign the interface.

## Required change record

Complete these fields for every change, including documentation-only changes:

```text
Change type: bug fix | feature | improvement | documentation
Problem or intent: what user/system behaviour changes and why
Evidence: failing test, log, reproduction, acceptance gap or design reason
Scope and owner: repository, authoritative files, dependency/runtime boundary
Acceptance criteria: observable conditions that define “done”
Tests: focused regression tests and the full required suite
Security/privacy: new fields, inputs, permissions, logs or trust assumptions
State and deployment: migrations, backups, runtime jobs, rollout and health checks
Rollback: source commit and any database/state restore needed
Documentation: README/spec/acceptance/runbook files updated
```

For a bug fix, include a regression test that fails before the fix and passes
after it whenever the behaviour can be automated. For a user-visible feature
or improvement, extend the relevant acceptance contract before declaring the
work complete. If a check cannot be automated, record the manual evidence and
the remaining limitation explicitly.

## 2. Establish evidence before mutation

- Check both repositories' branch and dirty state.
- Identify the authoritative source file and the deployed/runtime copy.
- For SQLite or migrations, take a consistent backup and test against a copy.
- Record the current failing behaviour without printing credentials or private
  message contents.
- Note the rollback commit and any state backup needed to return safely.

## 3. Implement behind the correct boundary

- Keep vendor payloads in their adapter. Normalize only reviewed fields.
- Use parameterized SQL and idempotent migrations.
- Preserve stable member IDs and idempotency keys.
- Bound network calls and payload sizes.
- Make unavailable, stale and permission-denied states explicit.
- Keep optional integrations disabled when config or credentials are absent.
- Never make a family-facing request wait on unbounded inference or vendor
  polling.

## 4. Verify by risk

Always run the agent-contract commands in `AGENTS.md`.

For ingestion/parsing changes, additionally verify:

- the happy path creates the required normalized row;
- a malformed attachment remains retryable;
- member and ISO week/year attribution are correct;
- rerunning does not duplicate facts.

For delivery changes, verify:

- both recipients are queued before sending;
- partial success retries only the failed recipient;
- lease expiry recovers interrupted work;
- vacation mode does not mark delivery sent;
- deterministic rendering works with inference disabled.

For portal changes, run in the sibling repository:

```bash
npm run docs:check
npm run lint
npm test
python3 tests/acceptance.py
```

For Smart Home changes, satisfy the acceptance criteria in
`specs/SMART_HOME.md`. Use read-only discovery before enabling commands.

The verification record must identify the exact commands run and their result;
“tests passed” without the command or scope is insufficient for a release
handoff. When two repositories participate in one feature, record the commit
used from each repository and verify their compatibility together.

## 5. Review privacy and security

- Inspect every new API field and log line.
- Confirm no token, password, cookie, raw email, raw Spond payload, precise
  private location or parent PIN enters Git or a browser response.
- Use a non-admin/least-privilege service account where the provider allows it.
- Require parent authorization for cameras and consequential commands.
- Keep LAN services unexposed to the public internet.

## 6. Promote and deploy

Commit intentional files on `dev`. Fast-forward verified `dev` to `main`; do
not rewrite production history. Follow `REDEPLOY.md`, deploy only the affected
service and inspect health/acceptance evidence before declaring success.

Documentation-only changes do not require restarting runtime services. A code,
configuration-contract, migration or LaunchAgent change does.

## 7. Update the handoff

Update all affected contracts in the same commit:

- `README.md` for supported capabilities and entry points;
- `ARCHITECTURE.md` for boundaries/topology;
- `CONFIGURATION.md` and the example for configuration changes;
- `CREDENTIALS.md` for authentication material;
- `SECURITY.md` for trust/threat changes;
- `specs/RELIABILITY.md` for core invariants;
- `specs/SMART_HOME.md` for appliance decisions;
- portal acceptance/data-boundary docs for user-visible/API changes.

Run `python3 scripts/validate_docs.py` last. A fresh session should be able to
locate the change surface, test command and rollback path without conversation
history.

## 8. Worked example: Ukeplan ingestion and presentation

The Ukeplan incident is the reference pattern for cross-repository fixes:

- Evidence: parent-sent school emails arrived with an empty IMAP subject; the
  PDF was present, but subject-only detection marked the email processed without
  storing a plan. A PDF template that stated only its ISO week also produced no
  deterministic day rows. The child overview read legacy day rows while the
  detail page read accepted interpretation data, so the two views disagreed.
- Core acceptance: detect Ukeplan signals from subject or message content,
  persist a plan before the email becomes terminal, recover recent stranded
  messages idempotently, and derive the Monday-Friday range from a valid ISO
  week when the PDF omits explicit dates. PDF content remains authoritative.
- Portal acceptance: expose only accepted, source-backed interpretation data in
  the curated dashboard contract and render the same interpretation on the
  child overview and detail page, with deterministic text/day facts as fallback.
- Verification: test blank-subject routing, parse real/template PDF variants,
  verify retry and no-duplicate recovery, run both repository suites, and make
  a live API/UI check for each affected child.
- Handoff: record the affected Core and Portal commits, the runtime deployment
  and backup, interpretation status, and the rollback source/state locations.

This example is intentionally about the method, not a private mailbox or
household-specific message ID. New changes should follow the same evidence →
acceptance → implementation → verification → deployment → documentation chain.
