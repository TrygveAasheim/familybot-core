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
ENABLED_LABELS="$("$PYTHON_BIN" - "$FAMILY_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

try:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    profile = config.get("profile") or "agent"
    integrations = config.get("integrations", {})
    notifications = config.get("notifications", {})
except (OSError, ValueError, AttributeError):
    raise SystemExit("Family configuration is missing or invalid")

def enabled(name):
    value = integrations.get(name)
    return isinstance(value, dict) and value.get("enabled", True) is not False

labels = set()
if profile in {"connected", "agent"}:
    labels.update({"familybot.health", "familybot.status"})
    if enabled("email"):
        labels.add("familybot.email")
    if enabled("spond") and integrations["spond"].get("groups"):
        labels.add("familybot.spond")
    if enabled("transport"):
        labels.add("familybot.tbane")
if profile == "agent":
    labels.add("familybot.delivery")
    if notifications.get("weekday_briefing", True) is not False:
        labels.add("familybot.briefing.weekday")
    if notifications.get("weekend_briefing", True) is not False:
        labels.add("familybot.briefing.weekend")
    if notifications.get("weekly_summary", True) is not False:
        labels.add("familybot.briefing.weekly")
    if enabled("email"):
        labels.add("familybot.ukeplan")
for label in sorted(labels):
    print(label)
PY
)"

for template in "$REPO_ROOT"/ops/launchd/familybot.*.plist.example; do
  filename="${template##*/}"
  plist_name="${filename%.example}"
  label="${filename%.plist.example}"
  target="$LAUNCH_AGENT_DIR/$plist_name"
  if ! printf '%s\n' "$ENABLED_LABELS" | grep -Fxq "$label"; then
    if [ "$RELOAD" -eq 1 ] && [ -e "$target" ]; then
      launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
      rm "$target"
      echo "Removed disabled generated job $target"
    fi
    echo "Skipped $label (not enabled by the selected capability profile)"
    continue
  fi
  temporary="$(mktemp "$LAUNCH_AGENT_DIR/.${label}.XXXXXX")"
  TEMPLATE_PATH="$template" TARGET_PATH="$temporary" WORKSPACE_VALUE="$WORKSPACE_DIR" \
    OPENCLAW_VALUE="$OPENCLAW_BIN" FAMILY_CONFIG_VALUE="$FAMILY_CONFIG" LABEL_VALUE="$label" \
    "$PYTHON_BIN" - <<'PY'
import json
import os
import plistlib
from pathlib import Path

template = Path(os.environ["TEMPLATE_PATH"])
target = Path(os.environ["TARGET_PATH"])
workspace = os.environ["WORKSPACE_VALUE"]
label = os.environ["LABEL_VALUE"]
content = template.read_text(encoding="utf-8").replace("__FAMILYBOT_WORKSPACE__", workspace)
document = plistlib.loads(content.encode("utf-8"))
config = json.loads(Path(os.environ["FAMILY_CONFIG_VALUE"]).read_text(encoding="utf-8"))
notifications = config.get("notifications", {})

def clock(name, fallback):
    value = str(notifications.get(name) or fallback)
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)

if label == "familybot.briefing.weekday":
    hour, minute = clock("weekday_time", "06:45")
    document["StartCalendarInterval"] = [
        {"Weekday": day, "Hour": hour, "Minute": minute} for day in range(1, 6)
    ]
elif label == "familybot.briefing.weekend":
    hour, minute = clock("weekend_time", "08:00")
    document["StartCalendarInterval"] = [
        {"Weekday": day, "Hour": hour, "Minute": minute} for day in (0, 6)
    ]
elif label == "familybot.briefing.weekly":
    hour, minute = clock("weekly_time", "21:00")
    weekdays = {
        "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
        "thursday": 4, "friday": 5, "saturday": 6,
    }
    day = weekdays.get(str(notifications.get("weekly_weekday") or "sunday"), 0)
    document["StartCalendarInterval"] = {"Weekday": day, "Hour": hour, "Minute": minute}
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
