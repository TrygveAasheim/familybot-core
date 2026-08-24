#!/bin/bash
# Lightweight cron runner — runs Python scripts WITHOUT loading an LLM session.
# Called by macOS launchd plists. No tokens spent.

set -u
umask 077

WORKSPACE="${FAMILYBOT_WORKSPACE:-$HOME/.openclaw/workspace}"
PYTHON="/usr/bin/python3"
LOG="$WORKSPACE/logs/cron.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

task="${1:-}"
case "$task" in
  email|spond|tbane|health|status|briefing-daily|briefing-weekly|delivery|ukeplan-interpret) ;;
  *)
    echo "Unknown task: $task" >&2
    exit 64
    ;;
esac

timestamp=$(date '+%Y-%m-%d %H:%M:%S')
LOCK_DIR="/tmp/familybot_${task}.lock"
PID_FILE="$LOCK_DIR/pid"

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$PID_FILE"
    return 0
  fi

  existing_pid=""
  if [ -r "$PID_FILE" ]; then
    existing_pid=$(sed -n '1p' "$PID_FILE")
  fi
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    return 1
  fi

  # A killed process can leave the directory behind. Remove only the exact,
  # validated task lock and acquire it again.
  unlink "$PID_FILE" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || return 1
  mkdir "$LOCK_DIR" 2>/dev/null || return 1
  echo "$$" > "$PID_FILE"
}

release_lock() {
  unlink "$PID_FILE" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

if ! acquire_lock; then
  echo "[$timestamp] $task skipped: previous run still active" >> "$LOG"
  exit 0
fi
trap release_lock EXIT INT TERM

case "$task" in
  email)
    echo "[$timestamp] email ingestion" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/process_emails.py" >> "$LOG" 2>&1
    ;;
  spond)
    echo "[$timestamp] spond sync" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/spond_sync.py" >> "$LOG" 2>&1
    ;;
  tbane)
    echo "[$timestamp] tbane monitor" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/tbane_monitor.py" >> "$LOG" 2>&1
    ;;
  health)
    echo "[$timestamp] health check" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/healthcheck.py" >> "$LOG" 2>&1
    ;;
  status)
    echo "[$timestamp] status update" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/update_status.py" >> "$LOG" 2>&1
    ;;
  briefing-daily)
    echo "[$timestamp] daily briefing" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/briefing.py" daily >> "$LOG" 2>&1
    ;;
  briefing-weekly)
    echo "[$timestamp] weekly briefing" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/briefing.py" weekly >> "$LOG" 2>&1
    ;;
  delivery)
    echo "[$timestamp] delivery outbox retry" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/flush_outbox.py" >> "$LOG" 2>&1
    ;;
  ukeplan-interpret)
    echo "[$timestamp] ukeplan interpretation" >> "$LOG"
    $PYTHON "$WORKSPACE/scripts/interpret_ukeplan.py" --limit 1 >> "$LOG" 2>&1
    ;;
esac
