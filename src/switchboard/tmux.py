"""The two tmux reads: every session, and every pane with its agent state and any sidebar's
endpoint."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from switchboard import panestate, run

ATTENTION = "@attention"
SIDEBAR = panestate.SIDEBAR
SESSION_FIELDS = (
    "session_name",
    "@wkt-worktree",
    "session_path",
    "session_last_attached",
    ATTENTION,
)
PANE_FIELDS = (
    "session_name",
    "window_index",
    "pane_index",
    "pane_id",
    "pane_current_command",
    *panestate.OPTIONS,
    SIDEBAR,
)


@dataclass(frozen=True)
class Session:
    name: str
    tag: str
    path: str
    last_attached: int = 0
    attention: str = ""


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
    agent: str = ""
    reasons: tuple[tuple[str, str], ...] = ()
    task: str = ""
    card_at: int = 0
    sidebar: str = ""
    index: int = 0
    session_id: str = ""

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
        Session(name, tag, path, _int(last), attention)
        for name, tag, path, last, attention in _rows(text, len(SESSION_FIELDS))
    ]


def parse_panes(text: str) -> list[Pane]:
    found = []
    for row in _rows(text, len(PANE_FIELDS)):
        name, win, index, pid, cmd, role, turn, keys, at, agent, why, task, card, sid, sidebar = row
        pending = panestate.decode_pending(keys)
        reasons = tuple(panestate.decode_reasons(why).items())
        stored = (role, turn, pending, _int(at), agent, reasons, panestate.decode_task(task))
        rest = (_int(card), sidebar, _int(index), sid)
        found.append(Pane(name, _int(win), pid, cmd, *stored, *rest))
    return found


def most_urgent(agents: Iterable[Pane]) -> Pane | None:
    """The agent that picking its session lands on: the most urgent, then a lead before a
    teammate, then the lowest window and pane."""
    return min(agents, key=_urgency, default=None)


def agents_by_session(panes: Iterable[Pane]) -> dict[str, tuple[Pane, ...]]:
    found: dict[str, list[Pane]] = defaultdict(list)
    for pane in panes:
        if pane.is_agent:
            found[pane.session].append(pane)
    return {session: tuple(agents) for session, agents in found.items()}


def _urgency(agent: Pane) -> tuple[int, bool, int, int]:
    rank = panestate.URGENCY.index(agent.state)
    return rank, agent.role == panestate.TEAMMATE, agent.window, agent.index


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
