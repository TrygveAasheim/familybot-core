#!/bin/bash
# Install the reviewed FamilyBot launchd templates for the current user.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_HOME="${HOME:?HOME is required}"
WORKSPACE_DIR="${FAMILYBOT_WORKSPACE:-$USER_HOME/.openclaw/workspace}"
LAUNCH_AGENT_DIR="${FAMILYBOT_LAUNCH_AGENTS_DIR:-$USER_HOME/Library/LaunchAgents}"
PYTHON_BIN="${FAMILYBOT_PYTHON:-$(command -v python3)}"
OPENCLAW_BIN="${FAMILYBOT_OPENCLAW:-$(command -v openclaw || true)}"
FAMILY_CONFIG="${FAMILYBOT_FAMILY_CONFIG:-$WORKSPACE_DIR/config/family.local.json}"
RELOAD=0

if [ "${1:-}" = "--reload" ]; then
  RELOAD=1
elif [ "${1:-}" != "" ]; then
  echo "Usage: $0 [--reload]" >&2
  exit 64
fi

"$PYTHON_BIN" "$SCRIPT_DIR/validate_launchd.py" --templates "$REPO_ROOT/ops/launchd"
install -d -m 700 "$LAUNCH_AGENT_DIR"
SPOND_ENABLED="$("$PYTHON_BIN" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

try:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    groups = config.get("integrations", {}).get("spond", {}).get("groups", [])
except (OSError, ValueError, AttributeError):
    groups = []
print("1" if isinstance(groups, list) and groups else "0")
PY
)"

for template in "$REPO_ROOT"/ops/launchd/familybot.*.plist.example; do
  filename="${template##*/}"
  plist_name="${filename%.example}"
  label="${filename%.plist.example}"
  target="$LAUNCH_AGENT_DIR/$plist_name"
  if [ "$label" = "familybot.spond" ] && [ "$SPOND_ENABLED" != "1" ]; then
    if [ "$RELOAD" -eq 1 ] && [ -e "$target" ]; then
      launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
      rm "$target"
      echo "Removed disabled generated job $target"
    fi
    echo "Skipped familybot.spond (optional Spond groups are not configured)"
    continue
  fi
  temporary="$(mktemp "$LAUNCH_AGENT_DIR/.${label}.XXXXXX")"
  TEMPLATE_PATH="$template" TARGET_PATH="$temporary" WORKSPACE_VALUE="$WORKSPACE_DIR" \
    OPENCLAW_VALUE="$OPENCLAW_BIN" "$PYTHON_BIN" - <<'PY'
import os
import plistlib
from pathlib import Path

template = Path(os.environ["TEMPLATE_PATH"])
target = Path(os.environ["TARGET_PATH"])
workspace = os.environ["WORKSPACE_VALUE"]
content = template.read_text(encoding="utf-8").replace("__FAMILYBOT_WORKSPACE__", workspace)
document = plistlib.loads(content.encode("utf-8"))
openclaw = os.environ.get("OPENCLAW_VALUE", "").strip()
if openclaw:
    document.setdefault("EnvironmentVariables", {})["FAMILYBOT_OPENCLAW"] = openclaw
target.write_bytes(plistlib.dumps(document, sort_keys=False))
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
