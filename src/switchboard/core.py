"""The core verbs on one pane's agent state, with its single read and single write.

An adapter (`switchboard.agents`) turns its agent's events into verbs. An event that changes
nothing makes one tmux read, with only light imports; a change adds one write, then the alert
and a refresh.
"""

from __future__ import annotations

import os
import time
from collections import namedtuple

from switchboard import panestate as ps
from switchboard import run

PANE_FORMAT = "\t".join(f"#{{{name}}}" for name in ("session_name", ps.ROLE, ps.TURN, ps.PENDING))
PID_FORMAT = f"{PANE_FORMAT}\t#{{pane_pid}}"
CLIENTS = ("list-clients", "-F", "#{client_name}\t#{client_session}")
ALL = "*"

Verb = namedtuple("Verb", ("name", "key"), defaults=("",))
State = namedtuple("State", ("pane", "role", "turn", "pending"))
View = namedtuple("View", ("session", "stored", "clients", "pid"), defaults=("",))
Stored = tuple[str, str, str]
Client = tuple[str, str]

START = Verb("start")
WORKING = Verb("working")
DONE = Verb("done")
IDLE = Verb("idle")
TEAMMATE = Verb("teammate")
END = Verb("end")
RESOLVE_ALL = Verb("resolve", ALL)
NAMED = {"start": START, "working": WORKING, "done": DONE, "idle": IDLE, "end": END}


def needs(key: str) -> Verb:
    return Verb("needs", ps.encode_pending([key]))


def resolve(key: str) -> Verb:
    return Verb("resolve", ps.encode_pending([key]))


def parse(args: list[str]) -> Verb | None:
    """The verb `switchboard state` names, or None when `args` are malformed."""
    match args:
        case [name] if name in NAMED:
            return NAMED[name]
        case ["resolve", "all"]:
            return RESOLVE_ALL
        case ["needs", key] if key:
            return needs(key)
        case ["resolve", key] if key:
            return resolve(key)
    return None


def split_agent(args: list[str]) -> tuple[str, list[str]] | None:
    """The `--agent NAME` in `args`, by default `claude`, and the other arguments; None when
    it's malformed."""
    agent, rest, items = ps.CLAUDE, [], iter(args)
    for arg in items:
        if arg == "--agent":
            agent = next(items, "")
        else:
            rest.append(arg)
    named = agent and all(c.isalnum() or c in "_.-" for c in agent)
    return (agent, rest) if named else None


def handle(adapter, event: str, payload: dict, pane: str, agent: str = ps.CLAUDE) -> None:
    """Applies `event` to `pane` through `adapter` (see `switchboard.agents`)."""
    if event not in adapter.HANDLED:
        return
    early = getattr(adapter, "early", None)
    verbs = early(event, payload) if early else None
    if verbs is not None:
        if verbs:
            perform(pane, verbs, agent)
        return
    view = read(pane, agent)
    if view is not None:
        role, turn, pending = view.stored
        state = State(pane, role, turn, ps.decode_pending(pending))
        settle(pane, view, adapter.verbs(event, payload, state), agent)


def perform(pane: str, verbs: list[Verb], agent: str = ps.CLAUDE) -> None:
    """Applies `verbs` to `pane`, reading it first unless they end a Claude agent."""
    if END in verbs and agent == ps.CLAUDE:
        end(pane)
        return
    view = read(pane, agent)
    if view is not None:
        settle(pane, view, verbs, agent)


def settle(pane: str, view: View, verbs: list[Verb], agent: str) -> None:
    if END in verbs:
        if placed(view, agent):
            end(pane)
        return
    viewed = any(where == view.session for _, where in view.clients)
    state = apply(view.stored, verbs, viewed)
    if state != view.stored and placed(view, agent):
        write(pane, state, agent)
        changed(view.session, view.stored, state, view.clients)


def placed(view: View, agent: str) -> bool:
    """Whether the event surely belongs to the pane. Claude's always do; another agent may run
    in a daemon whose `$TMUX_PANE` is another pane's, so its events must come from inside."""
    return agent == ps.CLAUDE or ancestor(view.pid)


def ancestor(pid: str) -> bool:
    """Whether process `pid` is this process or one of its ancestors."""
    out = run.output("ps", "-axo", "pid=,ppid=") or ""
    parents = dict(pair for pair in map(str.split, out.splitlines()) if len(pair) == 2)
    current, seen = str(os.getpid()), set()
    while current and current not in seen:
        if current == pid:
            return True
        seen.add(current)
        current = parents.get(current, "")
    return False


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


def read(pane: str, agent: str = ps.CLAUDE) -> View | None:
    """The pane's session, its stored state, each client's name and session, and for any agent
    but Claude, the pane's process id."""
    guarded = agent != ps.CLAUDE
    fmt = PID_FORMAT if guarded else PANE_FORMAT
    out = run.tmux(("display-message", "-p", "-t", pane, fmt), CLIENTS)
    if out is None:
        return None
    first, *lines = out.split("\n")
    fields = first.split("\t")
    if len(fields) != 4 + guarded:
        return None
    session, role, turn, pending, *pid = fields
    clients = [(name, where) for name, tab, where in (s.partition("\t") for s in lines) if tab]
    return View(session, (role, turn, pending), clients, *pid)


def write(pane: str, state: Stored, agent: str = ps.CLAUDE) -> None:
    role, turn, pending = state
    commands = [
        ("set-option", "-p", "-t", pane, ps.ROLE, role),
        ("set-option", "-p", "-t", pane, ps.TURN, turn),
        ("set-option", "-p", "-t", pane, ps.AT, str(int(time.time()))),
        ("set-option", "-p", "-t", pane, ps.AGENT, agent),
        ("set-option", "-p", "-t", pane, ps.PENDING, pending)
        if pending
        else ("set-option", "-p", "-u", "-t", pane, ps.PENDING),
    ]
    run.tmux(*commands)
