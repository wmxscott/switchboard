"""The pane options that hold a Claude agent's state: the hook writes them, the rest read them.

`@switchboard-at` holds Unix seconds. The hook imports this module, so it imports nothing heavy.
"""

from __future__ import annotations

from collections.abc import Iterable

ROLE = "@switchboard-role"
TURN = "@switchboard-turn"
PENDING = "@switchboard-pending"
AT = "@switchboard-at"
OPTIONS = (ROLE, TURN, PENDING, AT)

LEAD = "lead"
TEAMMATE = "teammate"
ROLES = (LEAD, TEAMMATE)

WORKING = "working"
DONE = "done"
IDLE = "idle"
TURNS = (WORKING, DONE, IDLE)

NEEDS = "needs"
URGENCY = (NEEDS, DONE, WORKING, IDLE)

LEAD_KEY = "lead"


def encode_pending(keys: Iterable[str]) -> str:
    """Sorted and comma-separated, each key limited to letters, digits, `_`, `.` and `-`, so a
    value never holds a comma, tab, newline or tmux's `;`."""
    safe = ("".join(c if c.isalnum() or c in "_.-" else "_" for c in key) for key in keys)
    return ",".join(sorted({key for key in safe if key}))


def decode_pending(value: str) -> tuple[str, ...]:
    return tuple(key for key in value.split(",") if key)


def display(turn: str, pending: tuple[str, ...]) -> str:
    if pending:
        return NEEDS
    return turn if turn in TURNS else IDLE


def most_urgent(states: Iterable[str]) -> str | None:
    return min(states, key=URGENCY.index, default=None)
