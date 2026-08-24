# Ukeplan interpretation

The original PDF is now the semantic source of truth. Its path is retained in
`week_plans.layout_json`, while deterministic `week_plan_days` rows continue
to support the dashboard and briefings. The PDF parser's page blocks remain
available as a local validation/fallback representation, not as the primary
LLM input.

Every fifteen minutes, `familybot.ukeplan` may interpret one stored plan with
the local OpenClaw model. The worker accepts only strict JSON whose item text
is found verbatim in the referenced PDF blocks, whose dates belong to the
plan's Monday–Friday ISO week, and whose categories are from the documented
allowlist. The result is stored in `week_plan_interpretations`. Every item must
also cite one or more PDF pages and use wording found in those pages.

The portal exposes an interpretation only when its status is `accepted`.
Until then, or after any model, timeout, JSON, or validation failure, it shows
the deterministic layout-preserving text and day facts. No LLM failure can
prevent email completion, plan persistence, or Telegram delivery.
