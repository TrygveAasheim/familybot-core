#!/usr/bin/env python3
"""Retry due outbound messages without invoking an LLM."""

import subprocess
import sys

from briefing import OPENCLAW, vacation_mode_active
from reliability import DeliveryOutbox


def send_telegram(target: str, message: str) -> bool:
    result = subprocess.run(
        [
            OPENCLAW,
            "message",
            "send",
            "--channel",
            "telegram",
            "--target",
            target,
            "--message",
            message,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()[:300]
        print(f"[outbox] Telegram delivery failed for {target}: {detail}")
        return False
    return True


def main() -> int:
    if vacation_mode_active():
        print("[outbox] Vacation mode active; retry deferred.")
        return 0

    outbox = DeliveryOutbox()
    result = outbox.deliver_pending(send_telegram, limit=50)
    counts = outbox.counts()
    print(
        f"[outbox] sent={result.sent} failed={result.failed} "
        f"expired={result.expired} pending={counts['pending']}"
    )
    return 2 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
