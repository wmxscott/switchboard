"""`@attention`: each session's status bar names the other sessions that need the user or are done.

The value is a tmux format that `status-right` shows with `#{E:@attention}`.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Iterable, Mapping, Sequence

from switchboard import panestate as ps
from switchboard import run, tmux
from switchboard.tmux import Pane, Session

BUDGET = 60
GAP = "  "
SHOWN = (ps.NEEDS, ps.DONE)
MARK = {ps.NEEDS: "▲", ps.DONE: "✓"}
COLOUR = {ps.NEEDS: "themeyellow", ps.DONE: "themegreen"}
HINT = ("themelightgrey", "prefix w")


def refresh() -> None:
    sessions = tmux.sessions()
    if sessions:
        _write(sessions, tmux.panes())


def seen(session: str) -> None:
    """Turns `session`'s done agents idle, keeping any pending prompts, then refreshes."""
    sessions = tmux.sessions()
    if not sessions:
        return
    panes = tmux.panes()
    done = {p.id for p in panes if p.session == session and p.is_agent and p.turn == ps.DONE}
    if done:
        now = str(int(time.time()))
        run.tmux(
            *(
                command
                for pane in sorted(done)
                for command in (
                    ("set-option", "-p", "-t", pane, ps.TURN, ps.IDLE),
                    ("set-option", "-p", "-t", pane, ps.AT, now),
                )
            )
        )
        panes = [dataclasses.replace(p, turn=ps.IDLE) if p.id in done else p for p in panes]
    _write(sessions, panes)


def current_session() -> str | None:
    """The session of `$TMUX_PANE`, else of the current client; None outside tmux."""
    pane = os.environ.get("TMUX_PANE")
    if not pane and not os.environ.get("TMUX"):
        return None
    target = ("-t", pane) if pane else ()
    out = run.output("tmux", "display-message", "-p", *target, "#{session_name}")
    return (out or "").removesuffix("\n") or None


def render(states: Mapping[str, str | None], own: str) -> str:
    """`own`'s value: the other sessions that need the user, then those that are done."""
    names = {
        state: sorted((n for n, s in states.items() if s == state and n != own), key=_order)
        for state in SHOWN
    }
    entries = [(COLOUR[state], f"{MARK[state]} {name}") for state in SHOWN for name in names[state]]
    if len(GAP.join(text for _, text in entries)) > BUDGET:
        entries = [
            (COLOUR[state], _count(state, len(names[state]))) for state in SHOWN if names[state]
        ]
        entries.append(HINT)
    if not entries:
        return ""
    styled = GAP.join(f"#[fg={colour}]{text.replace('#', '##')}" for colour, text in entries)
    return f"{styled}#[default] "


def _write(sessions: Sequence[Session], panes: Iterable[Pane]) -> None:
    agents = tmux.agents_by_session(panes)
    states = {s.name: ps.most_urgent(a.state for a in agents.get(s.name, ())) for s in sessions}
    commands = []
    for session in sessions:
        value = render(states, session.name)
        if value != session.attention:
            commands.append(("set-option", "-t", f"={session.name}:", tmux.ATTENTION, value))
    run.tmux(*commands)


def _count(state: str, n: int) -> str:
    if state == ps.NEEDS:
        return f"{MARK[state]} {n} {'needs' if n == 1 else 'need'} you"
    return f"{MARK[state]} {n} done"


def _order(name: str) -> tuple[str, str]:
    return name.casefold(), name
