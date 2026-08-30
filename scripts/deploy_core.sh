#!/bin/bash
# Deploy reviewed core scripts and launchd schedules to the private workspace.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME is required}"
WORKSPACE_DIR="${FAMILYBOT_WORKSPACE:-$USER_HOME/.openclaw/workspace}"

CURRENT_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
if [ "$CURRENT_BRANCH" != "dev" ]; then
  echo "Refusing deployment from '$CURRENT_BRANCH'. Deploy only from dev." >&2
  exit 1
fi

if [ "${1:-}" != "" ] && [ "${1:-}" != "--reload" ]; then
  echo "Usage: $0 [--reload]" >&2
  exit 64
fi

python3 "$SCRIPT_DIR/validate_launchd.py" --templates "$REPO_ROOT/ops/launchd"
install -d -m 700 "$WORKSPACE_DIR/scripts"

for source in "$REPO_ROOT"/scripts/*.py; do
  install -m 600 "$source" "$WORKSPACE_DIR/scripts/$(basename "$source")"
done
install -m 700 "$REPO_ROOT/scripts/cron_runner.sh" "$WORKSPACE_DIR/scripts/cron_runner.sh"

"$SCRIPT_DIR/install_launchagents.sh" "${1:-}"
echo "Core scripts and LaunchAgents deployed to $WORKSPACE_DIR"
