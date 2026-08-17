# Architecture

## Overview

```
┌─────────────────────────────────────────────────────┐
│                   Mac mini (local)                   │
│                                                      │
│  ┌──────────┐    ┌──────────────────────────────┐   │
│  │ Telegram │◄──►│         OpenClaw Gateway      │   │
│  │   Bot    │    │   (routing, sessions, agent)  │   │
│  └──────────┘    └──────────────┬───────────────┘   │
│                                 │                    │
│                    ┌────────────▼────────────┐       │
│                    │      FamilyBot Agent    │       │
│                    │  (context, memory,      │       │
│                    │   skill orchestration)  │       │
│                    └────────────┬────────────┘       │
│                                 │                    │
│          ┌──────────────────────┼──────────────┐     │
│          │                      │              │     │
│  ┌───────▼──────┐  ┌────────────▼───┐  ┌──────▼───┐ │
│  │ Skill:       │  │ Skill:         │  │ Skill:   │ │
│  │ Email        │  │ Spond          │  │ Kanban   │ │
│  │ Ingestion    │  │ Monitor        │  │ Board    │ │
│  └───────┬──────┘  └────────────┬───┘  └──────────┘ │
│          │                      │                    │
│  ┌───────▼──────┐  ┌────────────▼───┐               │
│  │ Skill:       │  │  Spond API     │               │
│  │ PDF Parser   │  │  (external)    │               │
│  └──────────────┘  └────────────────┘               │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │           Daily Briefing Scheduler           │   │
│  │         (cron job, runs each morning)        │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              Local Storage                   │   │
│  │  memory/, kanban.json, email-cache/,         │   │
│  │  spond-cache/, parsed-pdfs/                  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Components

### OpenClaw Gateway
Thin interaction layer. Handles Telegram connection, per-user sessions, routing and
interactive LLM calls. It does not schedule deterministic ingestion or monitoring jobs.

### macOS launchd
Single scheduler for email, Spond, status, health, T-bane and briefings. Jobs call
`scripts/cron_runner.sh`, which prevents overlapping runs. Python scripts remain usable
manually and do not require an agent session merely to start.

The reliability branch adds a five-minute delivery worker. The runner validates task
names and uses a recoverable PID lock, so a killed process cannot silently disable a
job forever.

### Reliability layer

`scripts/reliability.py` is deliberately independent of OpenClaw and inference. It owns:

- safe SQLite connections (`foreign_keys=ON`, bounded busy timeout),
- atomic JSON/text state replacement,
- the durable, idempotent Telegram outbox,
- the retryable email-processing ledger.

Inference is a presentation enhancement. Structured collection, deterministic fallback,
queueing, retries and health reporting continue to operate when the model is unavailable.
See `specs/RELIABILITY.md` for invariants and promotion checks.

### FamilyBot Agent
The main agent brain. Maintains:
- Per-user session context (configured parents have separate sessions)
- Long-term memory in `MEMORY.md` and `memory/YYYY-MM-DD.md`
- Skill orchestration — knows how to call each skill and combine results

### Skill: Email Ingestion
- Monitors a dedicated email inbox (IMAP)
- Accepts forwarded emails from school apps and other family sources
- Extracts plain text and identifies attachments (especially PDFs)
- Passes PDF attachments to the PDF Parser skill
- Stores processed emails in `email-cache/` with a parsed summary
- Tags emails by type: school, activity, admin, other

**Trigger:** Polling interval (every 15–30 minutes) or push via webhook if supported by email provider

### Skill: PDF Parser
- Accepts a PDF file path or attachment
- Extracts text content using a local PDF library
- Passes extracted text to the LLM for structured summarisation
- Returns: title, date(s), key actions required, deadline (if any), source
- Caches parsed results in `parsed-pdfs/` to avoid re-parsing

**Trigger:** Called by Email Ingestion skill when a PDF attachment is found

### Skill: Spond Monitor
- Connects to Spond (unofficial API or session-based scraping)
- Monitors: events calendar, group chats, announcements, RSVP status, decisions
- Identifies new or changed items since last check
- Flags items that require a response (RSVP pending, decision requested)
- Stores state in `spond-cache/` to enable delta detection

**Trigger:** Polling interval (every 30–60 minutes). Higher frequency not needed — Spond is not real-time critical.

**Risk:** Spond has no official API. Implementation depends on reverse-engineered API or community client. This is the highest-risk skill.

### Skill: Kanban Board
- A simple local kanban store (SQLite `kanban_cards` table)
- Three lanes: **To Do**, **In Progress**, **Done**
- Each card has: title, description, assigned-to (configured member or both), due date (optional), priority (must-do / nice-to / important), created-at, updated-at
- Both users can add, update, move, and complete cards via natural-language Telegram commands
- Completed cards are archived after 7 days
- **Scope:** Multi-day projects and ongoing tasks only. One-off school reminders and dated events go into `calendar_events`, not kanban.

**Commands (examples):**
- "Legg til: bestill tannlege for barnet" → creates card in To Do
- "Hva er på listen min?" → returns cards assigned to that user
- "Merk tannlege som ferdig" → moves card to Done

### Calendar Events
- Single table (`calendar_events`) aggregates all dated items from all sources: email/ukeplan, AKS, Spond, manual
- Fields: title, date, time, member, bring/prepare, requires_response, source
- This is the backbone of the daily briefing — everything time-bound lands here
- Sources tag their entries so origin is always traceable

### Daily Briefing Scheduler
- Runs every morning via macOS launchd
- Aggregates output from all skills
- Uses inference for natural language when available and deterministic rendering otherwise
- Queues separate, idempotent deliveries for every configured parent before sending
- Retries only failed recipients; expires stale daily/weekly briefings

**Briefing structure:**
```
Good morning [Name] — here's your day:

MUST DO
• [items with today's deadline or RSVP due]

IMPORTANT
• [time-sensitive items in the next 3 days]

NICE TO
• [kanban items without deadlines, lower priority]

THIS WEEK
• [upcoming Spond events, school dates]

---
[N] new emails processed · Last Spond check: 08:15
```

## Data Flow

```
Email arrives → processing ledger → routing → (PDF?) → PDF Parser → durable structured facts
                                                              │
Spond poll ──────────────────────────────────────────────────┤
                                                              │
Kanban state ────────────────────────────────────────────────┤
                                                              ▼
                                               Deterministic briefing data
                                                              │
                                                  inference (optional)
                                                              │
                                                      delivery outbox
                                                              │
                                                    ┌─────────┴──────────┐
                                                    ▼                    ▼
                                            Parent 1 Telegram    Parent 2 Telegram
```

## Session & Context Model

- Each Telegram user maps to their own OpenClaw session
- The `dmScope: per-channel-peer` setting (already configured) ensures this
- Shared data (kanban, Spond, school emails) lives in shared storage accessible to both sessions
- Personal preferences (briefing time, language, format) are stored per-user in memory

## Phase 1 Delivery Order

1. **Kanban board** — lowest risk, highest immediate value, no external dependencies
2. **Email ingestion + PDF parser** — needs email address setup first
3. **Daily briefing** — can start with kanban + email only, add Spond later
4. **Spond monitor** — highest risk, tackled last when API approach is confirmed
