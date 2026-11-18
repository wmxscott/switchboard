"""Running a command with a timeout, and tmux commands chained into one invocation."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

TIMEOUT = 2


def tmux(*commands: Sequence[str]) -> str | None:
    """Runs `commands` in one tmux invocation, chained with `;`."""
    args: list[str] = []
    for command in commands:
        args += [";", *command] if args else command
    return output("tmux", *args) if args else None


def output(*argv: str, timeout: float | None = None) -> str | None:
    """Its output, or None when it can't start, fails or is too slow."""
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT if timeout is None else timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None
