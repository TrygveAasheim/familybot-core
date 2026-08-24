#!/bin/bash
# Install the reviewed FamilyBot launchd templates for the current user.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME is required}"
WORKSPACE_DIR="${FAMILYBOT_WORKSPACE:-$USER_HOME/.openclaw/workspace}"
LAUNCH_AGENT_DIR="${FAMILYBOT_LAUNCH_AGENTS_DIR:-$USER_HOME/Library/LaunchAgents}"
RELOAD=0

if [ "${1:-}" = "--reload" ]; then
  RELOAD=1
elif [ "${1:-}" != "" ]; then
  echo "Usage: $0 [--reload]" >&2
  exit 64
fi

python3 "$SCRIPT_DIR/validate_launchd.py" --templates "$REPO_ROOT/ops/launchd"
install -d -m 700 "$LAUNCH_AGENT_DIR"

for template in "$REPO_ROOT"/ops/launchd/familybot.*.plist.example; do
  filename="${template##*/}"
  plist_name="${filename%.example}"
  label="${filename%.plist.example}"
  target="$LAUNCH_AGENT_DIR/$plist_name"
  temporary="$(mktemp "$LAUNCH_AGENT_DIR/.${label}.XXXXXX")"
  TEMPLATE_PATH="$template" TARGET_PATH="$temporary" WORKSPACE_VALUE="$WORKSPACE_DIR" python3 - <<'PY'
import os
from pathlib import Path

template = Path(os.environ["TEMPLATE_PATH"])
target = Path(os.environ["TARGET_PATH"])
workspace = os.environ["WORKSPACE_VALUE"]
target.write_text(template.read_text(encoding="utf-8").replace("__FAMILYBOT_WORKSPACE__", workspace), encoding="utf-8")
target.chmod(0o600)
PY
  mv "$temporary" "$target"
  echo "Installed $target"

  if [ "$RELOAD" -eq 1 ]; then
    if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
      launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        if ! launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
          break
        fi
        sleep 0.1
      done
    fi
    launchctl bootstrap "gui/$(id -u)" "$target"
    echo "Reloaded $label"
  fi
done
