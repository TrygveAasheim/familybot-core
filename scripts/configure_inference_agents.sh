#!/bin/bash
# Reconcile tool-free agents used for prompts containing email and PDF content.

set -euo pipefail

OPENCLAW_BIN="${FAMILYBOT_OPENCLAW:-$(command -v openclaw || true)}"

if [[ -z "$OPENCLAW_BIN" || ! -x "$OPENCLAW_BIN" ]]; then
  echo "OpenClaw is unavailable; inference-agent configuration skipped." >&2
  exit 0
fi

configure_agent() {
  local agent_id="$1"
  local model="$2"
  local agent_root
  local agent_workspace
  local agent_index

  if [[ ! "$agent_id" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]]; then
    echo "Invalid inference agent id." >&2
    exit 64
  fi
  if [[ ! "$model" =~ ^[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "Invalid inference model id." >&2
    exit 64
  fi

  agent_root="$HOME/.openclaw/agents/$agent_id"
  agent_workspace="$agent_root/workspace"
  install -d -m 700 "$agent_root" "$agent_workspace"

  if ! "$OPENCLAW_BIN" agents list --json | /usr/bin/python3 -c \
    'import json,sys; target=sys.argv[1]; raise SystemExit(0 if any(item.get("id")==target for item in json.load(sys.stdin)) else 1)' \
    "$agent_id"; then
    "$OPENCLAW_BIN" agents add "$agent_id" \
      --workspace "$agent_workspace" \
      --agent-dir "$agent_root/agent" \
      --model "$model" \
      --non-interactive \
      --json >/dev/null
  fi

  agent_index="$("$OPENCLAW_BIN" config get agents.list --json | /usr/bin/python3 -c \
    'import json,sys; target=sys.argv[1]; items=json.load(sys.stdin); print(next(index for index,item in enumerate(items) if item.get("id")==target))' \
    "$agent_id")"
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].model" "\"$model\"" --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].tools.profile" '"minimal"' --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].tools.allow" '[]' --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].tools.alsoAllow" '[]' --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].tools.elevated.enabled" 'false' --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].tools.deny" \
    '["group:runtime","group:fs","group:web","group:memory","group:ui","group:automation","group:messaging","group:nodes","group:agents","group:media","group:plugins","cron","gateway"]' \
    --strict-json >/dev/null
  "$OPENCLAW_BIN" config set "agents.list[$agent_index].skills" '[]' --strict-json >/dev/null
}

configure_agent \
  "${FAMILYBOT_BRIEFING_AGENT:-familybot-briefing}" \
  "${FAMILYBOT_BRIEFING_MODEL:-openai/gpt-5.6-sol}"
configure_agent \
  "${FAMILYBOT_UKEPLAN_AGENT:-familybot-ukeplan}" \
  "${FAMILYBOT_UKEPLAN_MODEL:-openai/gpt-5.6-sol}"

"$OPENCLAW_BIN" config validate >/dev/null
echo "Dedicated tool-free briefing and school-plan agents configured."
