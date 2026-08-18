# Roadmap

## Foundation — Core family organiser

- [x] Kanban storage and Telegram command surface
- [x] Email ingestion and processing ledger
- [x] `ukeplan` PDF/text parsing and normalized storage
- [x] Spond event synchronization through a community client
- [x] Deterministic daily/weekly briefing fallbacks and durable delivery outbox
- [x] Canonical local family configuration and validation
- [x] iPad-first LAN portal with family, child and parent surfaces
- [ ] Clean-room core database migration and complete LaunchAgent installer
- [ ] Complete configured-parent onboarding and preference management

## Uavklarte tekniske punkt

### Spond chat-meldinger
Testet 2026-04-19. `get_messages()` i spond-biblioteket returnerer 404 for alle grupper — chat-API-et ser ikke ut til å fungere mot vår konto/grupper. Spond har sannsynligvis en separat chat-API som ikke er implementert i biblioteket.

Mulige veier videre:
- Aktivere e-postvarsler for Spond-grupper → meldinger havner i innboksen og prosesseres automatisk
- Reverse-engineere Spond chat-API manuelt
- Vente på at spond-biblioteket implementerer det

Status: ikke løst, ikke prioritert. Følges opp når det er aktuelt.

---

## Add-on track — Smart Home

The canonical plan, device inventory and acceptance criteria are in
[`SMART_HOME.md`](SMART_HOME.md). Current order:

- [ ] Install Home Assistant as an isolated broker on the Mac mini
- [ ] Integrate the home Roborock S5 locally without re-pairing
- [ ] Test the cabin Q5 Pro through the existing Xiaomi Home account
- [ ] Add a separate `/smart-home` portal page and parent-authorized controls
- [ ] Evaluate laundry, freezer, Nest and cabin climate only after Xiaomi passes

## Add-on track — Local discovery

### Oslo-events for barn og familier
Research gjort 2026-04-19. Anbefalte kilder:
- **TMDB API** (gratis nøkkel) — barnefilmer på kino i Oslo, aldersgrense, omtale
- **Ticketmaster/Billetservice API** — konserter, familieshow, Oslo-events
- **LLM-basert ukentlig søk** — supplement siden de fleste norske eventsider blokkerer scraping (VisitOslo 403, Oslo kommune 404, Filmweb JS-rendered)
- Nasjonalmuseet, Munchmuseet, TusenFryd — parseable ved behov

Implementasjon: TMDB for kino + ukentlig web-søk som oppsummeres og sendes til familien.



Features that enrich family life but are not core to the organiser function.

- [ ] "What's happening in Oslo for kids this week" — events scraper / API for family-relevant events in Oslo
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
