# Change protocol

Use this protocol for every behavioural change. The amount of evidence scales
with risk, but no production change skips classification, tests or rollback
thinking.

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
