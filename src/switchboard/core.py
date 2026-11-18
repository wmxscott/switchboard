"""The core verbs on one pane's agent state, with its single read and single write.

An adapter (`switchboard.agents`) turns its agent's events into verbs. An event that changes
nothing makes one tmux read, with only light imports; a change adds one write, then the alert
and a refresh.
"""

from __future__ import annotations

import time
from collections import namedtuple

from switchboard import panestate as ps
from switchboard import run

PANE_FORMAT = "\t".join(f"#{{{name}}}" for name in ("session_name", ps.ROLE, ps.TURN, ps.PENDING))
CLIENTS = ("list-clients", "-F", "#{client_name}\t#{client_session}")
ALL = "*"

Verb = namedtuple("Verb", ("name", "key"), defaults=("",))
State = namedtuple("State", ("pane", "role", "turn", "pending"))
View = namedtuple("View", ("session", "stored", "clients"))
Stored = tuple[str, str, str]
Client = tuple[str, str]

START = Verb("start")
WORKING = Verb("working")
DONE = Verb("done")
IDLE = Verb("idle")
TEAMMATE = Verb("teammate")
END = Verb("end")
RESOLVE_ALL = Verb("resolve", ALL)


def needs(key: str) -> Verb:
    return Verb("needs", ps.encode_pending([key]))


def resolve(key: str) -> Verb:
    return Verb("resolve", ps.encode_pending([key]))


def handle(adapter, event: str, payload: dict, pane: str) -> None:
    """Applies `event` to `pane` through `adapter` (see `switchboard.agents`)."""
    if event not in adapter.HANDLED:
        return
    early = getattr(adapter, "early", None)
    verbs = early(event, payload) if early else None
    if verbs is not None:
        if verbs:
            perform(pane, verbs)
        return
    view = read(pane)
    if view is not None:
        role, turn, pending = view.stored
        state = State(pane, role, turn, ps.decode_pending(pending))
        settle(pane, view, adapter.verbs(event, payload, state))


def perform(pane: str, verbs: list[Verb]) -> None:
    """Applies `verbs` to `pane`, reading it first unless they end the agent."""
    if END in verbs:
        end(pane)
        return
    view = read(pane)
    if view is not None:
        settle(pane, view, verbs)


def settle(pane: str, view: View, verbs: list[Verb]) -> None:
    if END in verbs:
        end(pane)
        return
    viewed = any(where == view.session for _, where in view.clients)
    state = apply(view.stored, verbs, viewed)
    if state != view.stored:
        write(pane, state)
        changed(view.session, view.stored, state, view.clients)


def apply(stored: Stored, verbs: list[Verb], viewed: bool) -> Stored:
    """The (role, turn, pending) that `verbs` make of `stored`. A pane with no role is a lead,
    and one with no turn is idle."""
    role, turn, pending = stored
    role = role if role in ps.ROLES else ps.LEAD
    turn = turn if turn in ps.TURNS else ps.IDLE
    keys = set(ps.decode_pending(pending))
    for name, key in verbs:
        match name:
            case "start":
                role, turn, keys = ps.LEAD, ps.IDLE, set()
            case "teammate":
                role = ps.TEAMMATE
            case "working":
                turn = ps.WORKING
            case "done":
                turn = ps.IDLE if role == ps.TEAMMATE or viewed else ps.DONE
            case "idle":
                turn = ps.IDLE
            case "needs":
                keys.add(key)
            case "resolve" if key == ALL:
                keys.clear()
            case "resolve":
                keys.discard(key)
    return role, turn, ps.encode_pending(keys)


def end(pane: str) -> None:
    run.tmux(*(("set-option", "-p", "-u", "-t", pane, option) for option in ps.OPTIONS))
    from switchboard import attention

    attention.refresh()


def changed(session: str, before: Stored, after: Stored, clients: list[Client]) -> None:
    """Alerts every client when none is viewing `session`, then refreshes `@attention`."""
    from switchboard import alert, attention

    news = alert.news(before, after)
    if news and all(where != session for _, where in clients):
        alert.send(news, session, [name for name, _ in clients])
    attention.refresh()


def read(pane: str) -> View | None:
    """The pane's session, its stored state, and each client's name and session."""
    out = run.tmux(("display-message", "-p", "-t", pane, PANE_FORMAT), CLIENTS)
    if out is None:
        return None
    first, *lines = out.split("\n")
    fields = first.split("\t")
    if len(fields) != 4:
        return None
    session, role, turn, pending = fields
    clients = [(name, where) for name, tab, where in (s.partition("\t") for s in lines) if tab]
    return View(session, (role, turn, pending), clients)


def write(pane: str, state: Stored) -> None:
    role, turn, pending = state
    commands = [
        ("set-option", "-p", "-t", pane, ps.ROLE, role),
        ("set-option", "-p", "-t", pane, ps.TURN, turn),
        ("set-option", "-p", "-t", pane, ps.AT, str(int(time.time()))),
        ("set-option", "-p", "-t", pane, ps.PENDING, pending)
        if pending
        else ("set-option", "-p", "-u", "-t", pane, ps.PENDING),
    ]
    run.tmux(*commands)
