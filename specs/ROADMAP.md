# Roadmap

## Foundation — Core family organiser

- [x] Kanban storage and Telegram command surface
- [x] Email ingestion and processing ledger
- [x] `ukeplan` PDF/text parsing and normalized storage
- [x] Spond event synchronization through a community client
- [x] Deterministic daily/weekly briefing fallbacks and durable delivery outbox
- [x] Canonical local family configuration and validation
- [x] iPad-first LAN portal with family, child and parent surfaces
- [x] Complete health-owned LaunchAgent templates and installer
- [x] Clean-room Core/Portal database initialization and migrations
- [x] Guided configured-household dashboard onboarding

## Uavklarte tekniske punkt

### Spond chat messages

The community client has not established a supported chat-message contract;
some account/group combinations return provider errors. FamilyBot therefore
does not describe Spond chat ingestion as supported.

Possible future paths:

- use account-owned Spond email notifications through normal mail ingestion;
- add a fixture-backed bounded adapter if the community library publishes a
  stable contract; or
- wait for an official provider API.

Status: unsupported and not on the release path.

---

## Add-on track — Smart Home

The canonical plan, device inventory and acceptance criteria are in
[`SMART_HOME.md`](SMART_HOME.md). Current order:

- [ ] Install Home Assistant as an isolated broker on the Mac mini
- [ ] Prove one fictional/test local vacuum adapter without re-pairing production devices
- [ ] Prove one remote-location cloud adapter behind an explicit consent boundary
- [ ] Add a separate `/smart-home` portal page and parent-authorized controls
- [ ] Evaluate laundry, freezer, Nest and cabin climate only after Xiaomi passes

## Add-on track — Local discovery

### Configured local events for families

Future discovery must take the municipality/region from household
configuration. Candidate sources include official municipal feeds, TMDB for
cinema metadata and Ticketmaster for events. Scraping or model-assisted search
must be an optional bounded supplement, not a default Oslo assumption.



Features that enrich family life but are not core to the organiser function.

- [ ] "What's happening near us this week" — configured-region event API
- [ ] "What's happening near our configured second location" — conditions, events, activities
- [ ] Artist tour tracker — monitor announcements for locally configured artists

## Expansion ideas

Not committed to, not designed for yet. Written down so they don't get lost.

- Kids as direct Telegram users (age-appropriate interface)
- Integration with Norwegian school systems if APIs become available
- Shared family photo/memory capture via Telegram
- Budget tracking / shared household expenses

---

*Add-ons must not alter core ingestion or delivery semantics. Promote only a
generic, reviewed interface into core.*
