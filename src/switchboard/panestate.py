"""The pane options that hold an agent's state: the hook writes them, the rest read them.

`@switchboard-at` holds Unix seconds, and `@switchboard-agent` the agent's name. The hook imports
this module, so it imports nothing heavy; the hook has loaded `json` already.

`@switchboard-reasons` holds why each pending key needs the user, oldest first, and
`@switchboard-task` the line of the prompt that started the turn, both as JSON so that no text
can end a tmux command with `;` or split the tab-separated read. `@switchboard-card-at` holds the
Unix seconds of the agent's latest prompt, or of its turn ending done.

`@switchboard-session-id` holds the agent's own session id, for another tool to read through
`#{@switchboard-session-id}`, so it's stored as it is, never encoded.

`@switchboard-sidebar` marks a sidebar's pane (see `switchboard.sidebar`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

ROLE = "@switchboard-role"
TURN = "@switchboard-turn"
PENDING = "@switchboard-pending"
AT = "@switchboard-at"
AGENT = "@switchboard-agent"
REASONS = "@switchboard-reasons"
TASK = "@switchboard-task"
CARD_AT = "@switchboard-card-at"
SESSION_ID = "@switchboard-session-id"
OPTIONS = (ROLE, TURN, PENDING, AT, AGENT, REASONS, TASK, CARD_AT, SESSION_ID)

SIDEBAR = "@switchboard-sidebar"
# A tmux format, not empty when the window it's expanded for has a sidebar.
SIDEBAR_OPEN = f"#{{P:#{{{SIDEBAR}}}}}"

CLAUDE = "claude"

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
CAP = 200


def encode_pending(keys: Iterable[str]) -> str:
    """Sorted and comma-separated, each key limited to letters, digits, `_`, `.` and `-`, so a
    value never holds a comma, tab, newline or tmux's `;`."""
    safe = ("".join(c if c.isalnum() or c in "_.-" else "_" for c in key) for key in keys)
    return ",".join(sorted({key for key in safe if key}))


def decode_pending(value: str) -> tuple[str, ...]:
    return tuple(key for key in value.split(",") if key)


def session_id(value: object) -> str:
    """`value` when it's at most `CAP` ASCII letters, digits, `_`, `.` and `-`, else "": a
    mangled id would name another session."""
    if not isinstance(value, str) or len(value) > CAP:
        return ""
    return value if all(c.isascii() and (c.isalnum() or c in "_.-") for c in value) else ""


def one_line(text: str) -> str:
    """`text` as a reason or task is stored: control characters dropped, each run of whitespace,
    newlines included, one space, and at most `CAP` characters."""
    kept = "".join(c for c in text if c.isspace() or not _control(c))
    return " ".join(kept.split())[:CAP].rstrip()


def first_line(text: object) -> str:
    """The first line of `text` that isn't blank, as a prompt's line; "" without one."""
    lines = text.splitlines() if isinstance(text, str) else []
    return next((line for line in lines if line.strip()), "")


def encode_reasons(reasons: Mapping[str, str]) -> str:
    return json.dumps(dict(reasons), ensure_ascii=False, separators=(",", ":")) if reasons else ""


def decode_reasons(value: str) -> dict[str, str]:
    """Each key's reason, in the order stored; a value that isn't a JSON object gives none."""
    return {key: reason for key, reason in _json(value, dict).items() if isinstance(reason, str)}


def encode_task(task: str) -> str:
    return json.dumps(task, ensure_ascii=False) if task else ""


def decode_task(value: str) -> str:
    return _json(value, str)


def display(turn: str, pending: tuple[str, ...]) -> str:
    if pending:
        return NEEDS
    return turn if turn in TURNS else IDLE


def most_urgent(states: Iterable[str]) -> str | None:
    return min(states, key=URGENCY.index, default=None)


def _control(c: str) -> bool:
    return c < " " or "\x7f" <= c < "\xa0"


def _json(value: str, kind: type):
    try:
        found = json.loads(value)
    except ValueError:
        return kind()
    return found if isinstance(found, kind) else kind()
