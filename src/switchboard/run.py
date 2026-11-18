"""Running a command that only reads, with a timeout."""

from __future__ import annotations

import subprocess

TIMEOUT = 2


def output(*argv: str) -> str | None:
    """Its output, or None when it can't start, fails or is too slow."""
    try:
        result = subprocess.run(
            argv, capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None
