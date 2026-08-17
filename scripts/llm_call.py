#!/usr/bin/env python3
"""
llm_call.py - Lightweight OpenClaw/Codex inference for FamilyBot scripts.
"""

import subprocess
import json
import sys

OPENCLAW = "/opt/homebrew/bin/openclaw"

def generate(prompt: str, model: str | None = None, max_tokens: int = 1024) -> str:
    """
    Generate text through OpenClaw's Codex/OpenAI runtime.

    model and max_tokens are kept for API compatibility with older call sites;
    OpenClaw controls model selection and output length through configuration.
    """
    cmd = [
        OPENCLAW,
        "agent",
        "--agent",
        "main",
        "--thinking",
        "low",
        "--message",
        prompt,
        "--json",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=90,
    )

    if result.returncode != 0:
        print(f"[llm_call] openclaw error: {result.stderr[:200]}", file=sys.stderr)
        return ""

    try:
        data = json.loads(result.stdout)
        payloads = data.get("result", {}).get("payloads", [])
        if payloads:
            return payloads[0].get("text", "").strip()
        if "error" in data:
            print(f"[llm_call] API error: {data['error']}", file=sys.stderr)
    except Exception as e:
        print(f"[llm_call] Parse error: {e}", file=sys.stderr)

    return ""


if __name__ == "__main__":
    text = generate("Si 'hei' på norsk. Kun det ordet.")
    print(f"Test: {text!r}")
