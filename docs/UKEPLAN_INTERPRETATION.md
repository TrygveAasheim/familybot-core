# Ukeplan interpretation

The original PDF is now the semantic source of truth. Its path is retained in
`week_plans.layout_json`, while deterministic `week_plan_days` rows continue
to support the dashboard and briefings. The PDF parser's page blocks remain
available as a local validation/fallback representation, not as the primary
LLM input.

Every fifteen minutes, `familybot.ukeplan` may interpret one stored plan with
the local OpenClaw model. PDF-backed plans use two passes: an extraction pass
and a completeness/classification review pass that rereads the original PDF.
The result has three buckets: weekday-specific `days`, whole-week actions in
`weekly_tasks`, and non-action notices in `general_info`. The worker accepts
only strict JSON whose item text is found in the referenced PDF blocks, whose
dates belong to the plan's Monday–Friday ISO week, and whose categories are
from the documented allowlist. Every item must cite one or more PDF pages.

If the review pass fails, the validated extraction pass is retained. If the
extraction pass fails, the interpretation remains failed and the portal uses
the deterministic fallback text.

The portal exposes an interpretation only when its status is `accepted`.
Until then, or after any model, timeout, JSON, or validation failure, it shows
the deterministic layout-preserving text and day facts. No LLM failure can
prevent email completion, plan persistence, or Telegram delivery.

## Incident pattern and permanent safeguards

Ukeplan emails from a parent may have an empty IMAP subject even though the
body contains the plan name and a PDF attachment. Subject-only classification
is therefore not sufficient. The ingestion contract is:

1. detect the Ukeplan signal from the subject or sanitized message/attachment
   metadata;
2. route the message to the child before storing it;
3. download and parse the PDF, treating the PDF as the semantic source of truth;
4. store the normalized plan and day facts before marking the email terminal;
5. run the validated LLM interpretation asynchronously and keep it retryable;
6. expose the accepted interpretation consistently in both the child overview
   and the full-plan view.

Some school PDFs state an ISO week but omit explicit calendar dates. The
deterministic parser derives the Monday-Friday dates from that valid week so
the dashboard does not have an empty day structure. It never invents events;
weekday items still require evidence from the PDF or an accepted interpretation.

When a previous run marked a Ukeplan email complete before storing its plan, the
bounded recent backfill repairs it by source message ID and is idempotent. A
successful recovery must be checked for one plan per child/week, correct member
attribution, day rows, interpretation status and dashboard visibility.

For future changes, use the cross-repository worked example and change-record
standard in [`docs/CHANGE_PROTOCOL.md`](CHANGE_PROTOCOL.md).
