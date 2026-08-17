# Vision

## What We Are Building

A proactive family organiser for a locally configured household, delivered primarily through a Telegram bot and family dashboard. The bot consolidates information from multiple sources — school communications, activity calendars, email, documents, and a shared task board — and surfaces what matters, when it matters, without requiring the family to go looking for it.

The core value is **reducing cognitive load for busy parents**. The bot handles aggregation, parsing, prioritisation, and daily briefings.

## Who It Serves

- **Parent 1** — primary technical owner; receives information in their preferred format and cadence
- **Parent 2** — co-owner; receives the same underlying information but may prefer different formats, summaries, or timing
- **The kids** — not direct users yet, but the subject of most of the planning

## Guiding Principles

1. **Proactive, not reactive.** The bot surfaces important things before you need to go looking. A daily briefing lands every morning. Time-sensitive items get flagged as they arrive.
2. **Per-person context.** Parents share family data but not necessarily preferences. The bot maintains separate context, communication style, and delivery preferences per user.
3. **One source of truth.** All inputs — emails, Spond, PDFs, kanban tasks — feed into a single unified picture of the day and week.
4. **Privacy wall between users.** Personal conversations stay with the individual user. Shared family data (tasks, events, school info) is visible to configured parents.
5. **Self-hosted.** Runs on the family Mac mini. No family data leaves the house except to the LLM API and configured external services (Spond, email).
6. **Extensible.** The architecture should make it straightforward to add new skills later without reworking the core.

## What Success Looks Like

- Each morning, configured parents receive a daily briefing on Telegram with what matters today
- School emails and PDFs are automatically parsed and surfaced — no manual reading of every forward
- Spond events, decisions, and chat updates are monitored and flagged when action is needed
- The kanban board is a shared, living list that both can add to and that feeds into the daily briefing
- Nothing important falls through the cracks
