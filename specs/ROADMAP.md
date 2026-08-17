# Roadmap

## Phase 1 — Core Family Organiser (current focus)

- [ ] Kanban board skill
- [ ] Dedicated email address setup
- [ ] Email ingestion skill (IMAP polling + parsing)
- [ ] PDF parser skill
- [ ] Spond monitor skill
- [ ] Daily briefing (07:30, per-user, consolidated)
- [ ] Configured-parent onboarding (first contact, preference capture)

## Uavklarte tekniske punkt

### Spond chat-meldinger
Testet 2026-04-19. `get_messages()` i spond-biblioteket returnerer 404 for alle grupper — chat-API-et ser ikke ut til å fungere mot vår konto/grupper. Spond har sannsynligvis en separat chat-API som ikke er implementert i biblioteket.

Mulige veier videre:
- Aktivere e-postvarsler for Spond-grupper → meldinger havner i innboksen og prosesseres automatisk
- Reverse-engineere Spond chat-API manuelt
- Vente på at spond-biblioteket implementerer det

Status: ikke løst, ikke prioritert. Følges opp når det er aktuelt.

---

## Phase 2 — Local Discovery (future)

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

## Phase 3 — Expansion (ideas only)

Not committed to, not designed for yet. Written down so they don't get lost.

- Kids as direct Telegram users (age-appropriate interface)
- Integration with Norwegian school systems if APIs become available
- Shared family photo/memory capture via Telegram
- Budget tracking / shared household expenses

---

*Phase 2 and 3 items should not influence Phase 1 architecture unless the cost of accommodation is near-zero.*
