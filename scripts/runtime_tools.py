"""Resolve operator-configurable command-line tools without assuming Homebrew's prefix."""

from __future__ import annotations

import os
import shutil


def executable(environment_name: str, command: str) -> str:
    """Return an explicit override, a PATH match, or the command for a useful OS error."""
    configured = os.environ.get(environment_name, "").strip()
    if configured:
        return os.path.expanduser(configured)
    return shutil.which(command) or command
