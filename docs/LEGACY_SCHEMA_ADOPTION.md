# Legacy routing-audit adoption

## Defect and scope

A private-copy upgrade rehearsal found an unversioned `routing_audit` table
without `quarantine`. `CREATE TABLE IF NOT EXISTS` cannot add a column to an
existing table, so Core baseline validation rejected it and rolled back.
Prior tests mostly constructed a current schema with its ledger removed;
that did not reproduce this earlier table shape.

Core now recognizes the historical audit columns/types and integer primary key
before adding the missing column during baseline adoption. Additional household
columns are retained; missing/mistyped expected columns fail closed. Adoption
runs in the existing backup/transaction/final-validation path. Failure rolls
back DDL and ledger insertion together. Existing `quarantine` fields are not
rewritten, and an already-versioned database with a missing field is rejected,
not repaired by replaying the baseline.

This fixes adoption into the existing Core-1 contract. It does not change the
baseline statements, recorded checksum, schema version, or Portal-2 contract.
There is no manual ledger stamping, reseeding, ingestion-state update or message
replay. Core and Portal still have separate migration transactions.

## Historical flag semantics

The added legacy column is nullable `INTEGER CHECK(quarantine IN (0,1))`:

- `NULL`: no flag was recorded; the historical decision is unknown.
- `0` / `1`: an explicitly recorded false / true routing decision.

Do not infer the flag from old subjects, notes or categories and do not present
unknown as successfully processed. The existing fresh-schema non-null default
is unchanged; newly routed decisions explicitly persist their actual boolean
on both fresh and adopted schemas. Older writers on an adopted schema leave
`NULL`, honestly indicating that they did not record the flag.

`resolve_sender` retains pre-adoption schema compatibility without performing
DDL. It updates the flag only for a newly inserted audit row, in the same
transaction. Duplicate routing attempts do not reinterpret historical rows.
`get_routing_audit` exposes unknown as `None`/JSON null; `get_quarantined` lists
only explicit true flags, not all historical unknowns. The processing ledger
and actual routing result remain the authoritative processing decisions.

## Acceptance and tests

Run with fictional configuration and the matched Portal source:

```bash
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest tests.test_legacy_routing_adoption
FAMILYBOT_FAMILY_CONFIG=tests/fixtures/family.test.json \
  python3 -m unittest discover -s tests -p 'test_*.py'
```

The regression fixture directly creates the historical routing table. Tests
cover preserved columns/rows, unknown flags, constraints, repeat adoption,
backup failure, validation failure, malformed shape/types, retained extensions
and existing flags, versioned corruption rejection, exact legacy restore,
new true/false decisions, duplicate preservation and old-writer-schema support.

The private-copy rehearsal on 2026-11-11 passed the full installer data upgrade
to Core 1 / Portal 2, repeated upgrade and exact original-row restore. All 27
original tables were compared using their original columns: only the expected
national-holiday refresh changed original data. The added audit column was NULL
for every historical row. Chores, rewards, school plans, school dates, ingestion
and delivery records were not reset by migration.

The new Portal API then started on that isolated upgraded copy. Four plan-detail
routes, parent login, negative authorization, fictional chore creation,
completion and approval passed. The awarded completion persisted after API
shutdown. Restore recovered the exact original schema/data afterward. Python
outbound connections were disabled; no provider credentials or scheduled jobs
were used. This is not live deployment, physical iPad, or provider acceptance.

## Rollout and rollback

Follow [the existing upgrade procedure](../REDEPLOY.md): explicit paths, reviewed
source pair, all writers stopped and fresh backups. This source fix does not
authorize a live migration or remove the remaining staged-runtime deployment
gates. A successful private rehearsal is necessary but not sufficient for
full-stack promotion. Retain the baseline source/runtime/configuration pair.

Restore with the supported `manage_database.py restore --writers-stopped` path
only when undoing executed data/schema changes; a source-only revert needs no
database restore. Restoration has been exercised against the original legacy
schema, without inventing version markers. Never delete SQLite sidecars or drop
the new column manually as a rollback shortcut.
