# Ukeplan interpretation

The PDF parser remains the source of truth. It preserves readable line blocks
and page/weekday evidence in `week_plans.layout_json`, while deterministic
`week_plan_days` rows continue to support the dashboard and briefings.

Every fifteen minutes, `familybot.ukeplan` may interpret one stored plan with
the local OpenClaw model. The worker accepts only strict JSON whose item text
is found verbatim in the referenced PDF blocks, whose dates belong to the
plan's Monday–Friday ISO week, and whose categories are from the documented
allowlist. The result is stored in `week_plan_interpretations`.

The portal exposes an interpretation only when its status is `accepted`.
Until then, or after any model, timeout, JSON, or validation failure, it shows
the deterministic layout-preserving text and day facts. No LLM failure can
prevent email completion, plan persistence, or Telegram delivery.
