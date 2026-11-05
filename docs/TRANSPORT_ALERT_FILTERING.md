# Transport alert filtering

## Change record

- Change type: bug fix and configuration improvement.
- Problem or intent: Entur may associate a station accessibility notice with a
  whole line. Line-only filtering can therefore send notices for stations
  outside a household's configured journey corridor.
- Evidence: a sanitized SIRI-SX fixture reproduces an elevator notice tagged
  with the configured line but scoped to a station outside the fictional test
  corridor.
- Scope and owner: Core owns Entur parsing and relevance in
  `scripts/transport_relevance.py`; `tbane_monitor.py` owns immediate Telegram
  alerts and `briefing_data.py` owns briefing facts. Portal is unchanged.
- Acceptance criteria: station-scoped notices are retained only when an
  affected station intersects the configured corridor; general configured-line
  failures and genuinely system-wide failures remain; Telegram and briefings
  use the same decision; deployments without `alert_stops` retain compatible
  line-only behavior.
- Tests: recorded SIRI-SX fragments cover inside/outside elevator notices,
  structured stop metadata, general line failures and station-scoped versus
  genuine system-wide incidents. Run the complete Core test and preflight
  commands from `AGENTS.md`.
- Security/privacy: station names are local configuration and are not sent to a
  new provider or returned through a new API. No credentials or household
  member data are added.
- State and deployment: no database migration. Update private configuration,
  deploy reviewed Core scripts, then run the monitor once. Existing irrelevant
  active-alert state disappears on the next successful reconciliation.
- Rollback: redeploy the preceding Core commit and remove `alert_stops` from the
  private configuration. No database restore is required.
- Documentation: configuration fields and filtering semantics are documented in
  `CONFIGURATION.md` and `config/family.example.json`.

## Relevance rules

Entur line references are necessary but not sufficient. FamilyBot first parses
the line, summary, affected stop names and affected stop references from each
SIRI-SX situation. It then applies these rules:

1. Ignore configured noise categories such as minor-delay and generic
   wheelchair-suitability notices.
2. For a notice with affected stop metadata, require an intersection with
   `alert_stops` or, when configured, `alert_stop_ids`.
3. For an accessibility notice without structured stop metadata, retain it only
   when its summary names a corridor station.
4. Retain an otherwise unscoped operating notice for the configured line.
5. Apply the same corridor check before treating a notice tagged with four or
   more lines as system-wide.

This intentionally favors useful operational warnings while suppressing remote
station noise. If Entur changes its payload shape, the bounded adapter may fall
back to summary matching; fixture tests should be updated from a sanitized
recorded response before changing the rules.
