#!/bin/bash
# Deploy reviewed core scripts and launchd schedules to the private workspace.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME is required}"
WORKSPACE_DIR="${FAMILYBOT_WORKSPACE:-${OPENCLAW_WORKSPACE:-$USER_HOME/.familybot}}"
FAMILY_CONFIG="${FAMILYBOT_FAMILY_CONFIG:-$WORKSPACE_DIR/config/family.local.json}"
CORE_RUNTIME="$WORKSPACE_DIR/runtime/core"
UV_BIN="${FAMILYBOT_UV:-$(command -v uv || true)}"
HOST_PYTHON="${FAMILYBOT_PYTHON:-$(command -v python3 || true)}"

CURRENT_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
CURRENT_BRANCH="${CURRENT_BRANCH:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
DEPLOY_BRANCH="${FAMILYBOT_DEPLOY_BRANCH:-dev}"
if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
  echo "Refusing deployment from '$CURRENT_BRANCH'. Expected '$DEPLOY_BRANCH'." >&2
  echo "Fork maintainers may set FAMILYBOT_DEPLOY_BRANCH to their reviewed release branch." >&2
  exit 1
fi

if [ "${1:-}" != "" ] && [ "${1:-}" != "--reload" ]; then
  echo "Usage: $0 [--reload]" >&2
  exit 64
fi

if [ -z "$UV_BIN" ]; then
  echo "uv is required to build the isolated Core Python runtime (brew install uv)." >&2
  exit 1
fi
if [ -z "$HOST_PYTHON" ]; then
  echo "Python is required to validate the FamilyBot configuration." >&2
  exit 1
fi
"$HOST_PYTHON" "$SCRIPT_DIR/validate_config.py" --config "$FAMILY_CONFIG"
PROFILE="$("$HOST_PYTHON" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value.get("profile") or "agent")
PY
)"
ENABLED_ADAPTERS="$("$HOST_PYTHON" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
integrations = value.get("integrations", {})
for name in ("email", "spond"):
    settings = integrations.get(name)
    if isinstance(settings, dict) and settings.get("enabled", True) is not False:
        print(name)
PY
)"
if [ "$PROFILE" = "agent" ] && ! command -v openclaw >/dev/null 2>&1; then
  echo "The agent profile requires OpenClaw; install and verify it before deployment." >&2
  exit 1
fi
install -d -m 700 "$CORE_RUNTIME"
if [ ! -x "$CORE_RUNTIME/.venv/bin/python" ]; then
  "$UV_BIN" venv --python 3.12 "$CORE_RUNTIME/.venv"
fi
SYNC_FILES=("$REPO_ROOT/requirements-base.txt")
if printf '%s\n' "$ENABLED_ADAPTERS" | grep -Fxq "email"; then
  SYNC_FILES+=("$REPO_ROOT/requirements-email.txt")
fi
if printf '%s\n' "$ENABLED_ADAPTERS" | grep -Fxq "spond"; then
  SYNC_FILES+=("$REPO_ROOT/requirements-spond.txt")
fi
"$UV_BIN" pip sync --allow-empty-requirements \
  --python "$CORE_RUNTIME/.venv/bin/python" "${SYNC_FILES[@]}"
"$UV_BIN" pip check --python "$CORE_RUNTIME/.venv/bin/python"
CORE_PYTHON="$CORE_RUNTIME/.venv/bin/python"
"$CORE_PYTHON" "$SCRIPT_DIR/validate_launchd.py" --templates "$REPO_ROOT/ops/launchd"
if [ "$PROFILE" = "agent" ]; then
  "$SCRIPT_DIR/configure_inference_agents.sh"
  "$CORE_PYTHON" "$SCRIPT_DIR/configure_openclaw_model.py" --check
fi
install -d -m 700 \
  "$WORKSPACE_DIR/scripts" \
  "$WORKSPACE_DIR/logs" \
  "$WORKSPACE_DIR/memory" \
  "$WORKSPACE_DIR/backups" \
  "$WORKSPACE_DIR/db/job_state"

for source in "$REPO_ROOT"/scripts/*.py; do
  install -m 600 "$source" "$WORKSPACE_DIR/scripts/$(basename "$source")"
done
install -m 700 "$REPO_ROOT/scripts/cron_runner.sh" "$WORKSPACE_DIR/scripts/cron_runner.sh"

FAMILYBOT_PYTHON="$CORE_PYTHON" "$SCRIPT_DIR/install_launchagents.sh" "${1:-}"
echo "Core scripts and LaunchAgents deployed to $WORKSPACE_DIR"
