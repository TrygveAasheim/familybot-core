# Ukeplan interpretation

## Original document and independent reading

Portal's primary plan view renders the original PDF, preserving columns, tables
and page boundaries. Its local passive renderer does not depend on successful
interpretation. Stored text/accepted interpretation remain in a secondary
disclosure; Telegram briefings continue reading their existing bounded inputs.
Opening a document triggers no inference, ingestion, replay or delivery.

New ingestion preserves PDF text line/paragraph breaks and records
`layout_json.source_sha256` alongside the registered `source_pdf`. Portal reads
only registered PDFs below the private `db/attachments` root, bound to the
requested child/plan and local session. A recorded fingerprint mismatch blocks
display. Legacy rows without hashes remain compatible but cannot prove a mutable
historical file was never overwritten. Back up attachments with SQLite; a database
restore alone cannot recreate a missing PDF. No schema migration is needed.

This presentation change does not repair semantic extraction, invent missing
homework or retry existing failed interpretations. Historical flattened text
stays flattened until separately authorized reprocessing. Preserved newlines
are not reliable table cell/day relationships; future structured dashboard facts
still need source/day validation. Roll back code only, not household data.

## Interpretation pipeline

The original PDF is the source of task content. Explicit child and ISO week/year
metadata in a configured parent's email subject overrides reused PDF headings
and forwarded sender/body metadata. For example, `Ukeplan uke 43 Child Two 6A`
assigns that child's plan to week 43 even if the PDF says week 35. Without an
explicit subject week, the PDF week remains the fallback. Invalid or ambiguous
subject periods fail ingestion and remain retryable. An explicit year such as
`uke 1/2027` overrides the email receipt year. The PDF path is retained in
`week_plans.layout_json`, while deterministic `week_plan_days` rows continue
to support the dashboard and briefings. The PDF parser's page blocks remain
available as a local validation/fallback representation, not as the primary
LLM input.

Every fifteen minutes, `familybot.ukeplan` may interpret one stored plan with
OpenAI through OpenClaw (default `openai/gpt-5.6-sol`, configurable with
`FAMILYBOT_UKEPLAN_MODEL`). PDF-backed plans use two passes: an extraction pass
and a completeness/classification review pass that rereads the original PDF.
The result has three buckets: weekday-specific `days`, whole-week actions in
`weekly_tasks`, and non-action notices in `general_info`. The worker accepts
only strict JSON whose item text is found in the referenced PDF blocks, whose
dates belong to the plan's Monday–Friday ISO week, and whose categories are
from the documented allowlist. Every item must cite one or more PDF pages.

If the review pass fails, the validated extraction pass is retained. If the
extraction pass fails, the interpretation remains failed and the portal uses
the original PDF with secondary deterministic fallback text.

The portal exposes an interpretation only when its status is `accepted`.
Until then, or after any model, timeout, JSON, or validation failure, it shows
the original PDF with secondary stored text. Historical text may be flattened;
new line preservation alone does not reconstruct table relationships. No LLM failure can
prevent email completion, plan persistence, or Telegram delivery.

Source-preservation verification (2026-11-12): the full fictional Core suite ran
204 tests successfully (one skipped), including idempotent storage, source
fingerprints, missing-file failure before database access, preserved paragraphs
and the unchanged `briefing_data.week_plan` reading contract. Ruff, Bandit,
configuration/docs validation, Python compilation and shell syntax checks passed.
No existing household PDF was replayed and no Telegram message was sent.

## Incident pattern and permanent safeguards

Ukeplan emails from a parent may have an empty IMAP subject even though the
body contains the plan name and a PDF attachment. Subject-only classification
is therefore not sufficient. The ingestion contract is:

1. detect the Ukeplan signal from the subject or sanitized message/attachment
   metadata;
2. route the message to the child before storing it, preferring an unambiguous
   configured-parent subject;
3. download and parse the PDF for content, applying the parent's explicit
   subject period before deriving weekday dates;
4. store the normalized plan and day facts before marking the email terminal;
5. run the validated LLM interpretation asynchronously and keep it retryable;
6. expose the original PDF in the full-plan view, linked from the compact child
   overview, with accepted interpretation or stored text in a secondary disclosure.

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

## Subject-override regression and recovery

Acceptance: an old PDF header cannot overwrite another week's plan when the
parent explicitly supplies a week; all five weekday dates and the interpreter
use the resolved ISO period; source PDF text stays intact; rerunning produces
one child/week row; a changed plan immediately invalidates its interpretation.
`layout_json.attribution` records the resolved period and whether it came from
the parent subject or PDF, without publishing the email subject.

Before correcting an already misfiled plan, back up SQLite and deployed scripts.
Reparse the source into the correct child/week, validate the resulting day rows,
and restore the overwritten historical row and its dependent rows from a verified
pre-incident backup. Test this operation on a database copy first. Reinterpret
the corrected plan explicitly with `interpret_ukeplan.py --plan-id ID`, then
verify the portal detail view. Do not replay previously sent Telegram briefings
as part of a data repair.

Regression command:
`python3 -m unittest discover -s tests -p 'test_ukeplan_subject_and_briefing.py'`.
