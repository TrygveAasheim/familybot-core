# Architecture

FamilyBot is a local-first Norwegian family information service. Deterministic
jobs collect and store facts; optional inference improves wording; the iPad
dashboard and Telegram expose curated views.

## Physical topology

```mermaid
flowchart LR
  subgraph Internet["External services"]
    Mail["School email / Himalaya"]
    Spond["Spond community API"]
    MET["MET Norway"]
    Entur["Entur"]
    TG["Telegram"]
    Model["Configured inference provider"]
  end

  subgraph Home["Private home LAN"]
    Router["Home router + mDNS"]
    subgraph Mini["Always-on Mac mini"]
      Launchd["launchd schedules"]
      Core["FamilyBot Core jobs"]
      DB[("SQLite family.db")]
      Gateway["OpenClaw gateway"]
      API["Curated local API :8788"]
      Web["Familieportalen :3000"]
      Bonjour["Bonjour: Familieportalen"]
    end
    iPad["iPad / touch dashboard"]
    Parent["Parent phone"]
  end

  Mail --> Core
  Spond --> Core
  MET --> Core
  Entur --> API
  Launchd --> Core
  Core <--> DB
  Core --> Gateway
  Gateway <--> TG
  Gateway <--> Model
  DB --> API --> Web
  MET --> API
  Web --> Bonjour --> Router --> iPad
  TG --> Parent
```

The browser is a family appliance, not an OpenClaw administration console. It
cannot read raw email, credentials, raw Spond payloads or arbitrary files, and
it cannot trigger scheduled ingestion or Telegram delivery.

## Data and trust boundaries

```mermaid
flowchart TD
  Untrusted["Untrusted external content\nemail, PDFs, Spond"]
  Validate["Bounded parsing, routing, validation"]
  Facts["Structured facts in SQLite"]
  Curate["Explicit API field allowlist"]
  Child["Child session\nview + own completion"]
  Parent["Parent session\nPIN + rate limit"]
  Mutate["Validated chore/reward writes"]
  Audit["0600 local audit + backup"]
  LLM["Inference: wording only"]
  Outbox["Durable delivery outbox"]

  Untrusted --> Validate --> Facts --> Curate
  Curate --> Child
  Curate --> Parent
  Child --> Mutate
  Parent --> Mutate
  Mutate --> Audit
  Facts --> LLM --> Outbox
  Facts --> Outbox
```

Inference is outside the durability boundary. If it fails, deterministic
briefings, ingestion state, retries and dashboard data remain available.

## Runtime layout

```text
Git checkouts/                         reviewed, non-private source
  familybot-core/
  familybot-portal/

$HOME/.openclaw/workspace/            private durable state
  config/family.local.json
  db/family.db
  scripts/
  secrets.env
  attachments/, logs/, memory/, backups/

$HOME/.openclaw/runtime/familybot-portal/  generated deployed portal
$HOME/Library/LaunchAgents/                reviewed schedules/supervisors
```

Source control is not a household backup. See [REDEPLOY.md](REDEPLOY.md) for
the source/state/credential restore order and [SECURITY.md](SECURITY.md) for
the threat model.
