"""The two tmux reads: every session, and every pane with its agent state."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from switchboard import panestate, run

SESSION_FIELDS = ("session_name", "@wkt-worktree", "session_path", "session_last_attached")
PANE_FIELDS = (
    "session_name",
    "window_index",
    "pane_id",
    "pane_current_command",
    *panestate.OPTIONS,
)


@dataclass(frozen=True)
class Session:
    name: str
    tag: str
    path: str
    last_attached: int = 0


@dataclass(frozen=True)
class Pane:
    session: str
    window: int
    id: str
    command: str
    role: str = ""
    turn: str = ""
    pending: tuple[str, ...] = ()
    at: int = 0

    @property
    def is_agent(self) -> bool:
        return self.role in panestate.ROLES

    @property
    def state(self) -> str:
        return panestate.display(self.turn, self.pending)


def sessions() -> list[Session]:
    return parse_sessions(_query("list-sessions", SESSION_FIELDS))


def panes() -> list[Pane]:
    return parse_panes(_query("list-panes", PANE_FIELDS, "-a"))


def parse_sessions(text: str) -> list[Session]:
    return [
        Session(name, tag, path, _int(last))
        for name, tag, path, last in _rows(text, len(SESSION_FIELDS))
    ]


def parse_panes(text: str) -> list[Pane]:
    return [
        Pane(name, _int(window), pid, cmd, role, turn, panestate.decode_pending(pending), _int(at))
        for name, window, pid, cmd, role, turn, pending, at in _rows(text, len(PANE_FIELDS))
    ]


def agents_by_session(panes: Iterable[Pane]) -> dict[str, tuple[Pane, ...]]:
    found: dict[str, list[Pane]] = defaultdict(list)
    for pane in panes:
        if pane.is_agent:
            found[pane.session].append(pane)
    return {session: tuple(agents) for session, agents in found.items()}


def _query(command: str, fields: Iterable[str], *flags: str) -> str:
    fmt = "\t".join(f"#{{{field}}}" for field in fields)
    return run.output("tmux", command, *flags, "-F", fmt) or ""


def _rows(text: str, width: int) -> Iterator[list[str]]:
    for line in text.split("\n"):
        fields = line.split("\t")
        if len(fields) == width:
            yield fields


def _int(text: str) -> int:
    return int(text) if text.isdecimal() else 0
