# Constraints

## Hard Constraints

### Privacy
- One parent's private conversations with the bot are never shared with another parent
- Shared family data (events, tasks, school info) is visible to both
- Durable normalized family data remains local. Selected content may transit the
  configured inference provider and Telegram when those features are used.

### Infrastructure
- Runs on the family Mac mini (self-hosted, always-on)
- OpenClaw is the Telegram gateway and interactive agent runtime; launchd schedules deterministic work
- All persistent storage is local (files, JSON, SQLite as needed)
- No paid SaaS backends beyond what is already in use

### Reliability
- The daily briefing must send even if one or more skills fail — partial data with a clear note is better than silence
- Skills should fail gracefully and log errors without crashing the whole pipeline

### Cost
- LLM calls should be minimised where possible (prompt caching, batching, avoiding redundant calls)
- Spond polling and email checks should be reasonable in frequency — not hammering APIs

## Soft Constraints

### Tech stack
- Prefer JavaScript/TypeScript or Python for new skill code (whatever integrates cleanest with OpenClaw)
- Prefer existing libraries over building from scratch (e.g. existing Spond API clients if available)
- Keep external dependencies minimal and auditable

### Scope and add-on isolation
- The reliability core is email ingestion, weekly-plan parsing, normalized
  family facts, Spond/calendar inputs, deterministic briefings, durable delivery
  and health.
- Portal features, Smart Home, cameras, menu providers and local-event discovery
  are add-ons behind curated interfaces.
- An add-on must not change core completion semantics or make a core job depend
  on its availability. See `docs/REPOSITORY_GUIDE.md`.

### User experience
- The iPad-first LAN dashboard is the family's glanceable and child-facing
  interface. Telegram/OpenClaw is the conversational layer for complex actions.
- Commands should be simple and natural-language where possible
- The daily briefing should be scannable in under 60 seconds

## Lærte begrensninger (oppdatert 2026-04-19)

### Sesjonskonsistens
Telegram-sesjoner og isolerte cron-sesjoner starter fra scratch og har ikke tilgang til hovedsesjonens kontekst. Dette betyr:
- De kan ta feil av konfig, kapabiliteter og tidspunkt hvis de ikke leser de riktige filene
- Løsning: BOOT.md → SKILLS.md → STATUS.md må alltid leses ved oppstart
- STATUS.md regenereres hvert 30. min for å holde alle sesjoner synkronisert

### Tidshåndtering
- `exec date` er eneste pålitelige kilde til nåværende tid — alltid bruk dette
- Timestamp i innkommende meldinger er et hint, ikke fasit
- LLM-sesjoner må aldri gjette dato eller tid

### Dokumentasjonsplikt
- For every bug fix, feature and improvement, complete the change record in
  `docs/CHANGE_PROTOCOL.md` and update the relevant README, specification,
  acceptance, security, configuration or runbook contract in the same commit.
  Record the evidence, tests, deployment and rollback path; do not rely on
  conversation history.
- Hvis en feil avdekkes i dokumentasjon: rett det umiddelbart
- For conversational runtime orientation: STATUS.md (system) → MEMORY.md
  (family/context) → SKILLS.md (capabilities). This runtime hierarchy does not
  override normalized SQLite state, canonical configuration or reviewed source.

## Open Questions

- **Email address**: A dedicated email address needs to be set up for the bot to receive forwards from school apps. Provider TBD (could be a simple Gmail, Fastmail alias, or self-hosted).
- **Parent onboarding**: preferences such as format, timing, and language are captured locally on first contact.
- **Kids on Telegram**: Not currently planned. Children use the portal directly;
  adding child Telegram accounts later requires an explicit security boundary.
- **Spond API access**: Spond does not have an official public API. A third-party client or scraping approach will be needed — this is the highest technical risk item.
- **Norwegian language**: School communications and Spond content may be in Norwegian. Prompts and summaries use each locally configured preference.
