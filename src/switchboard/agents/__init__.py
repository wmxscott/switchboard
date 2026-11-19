"""Agent adapters: each turns one kind of agent's events into the core verbs on its pane.

An adapter is a module in this package, named for its agent: `switchboard hook --agent pi`
loads `agents/pi.py`, and an unknown name does nothing. It never runs tmux, which is
`switchboard.core`'s job. For any agent but Claude, an event is dropped unless the hook runs
inside the pane, as a descendant of its process. A tool with no adapter can run the verbs with
`switchboard state <verb> [--agent NAME]`, which takes `--reason` with `needs` and `--task` with
`working`. An adapter has:

`HANDLED`
    The event names it acts on. Any other event is dropped before tmux is touched.

`verbs(event, payload, state) -> list[core.Verb]`
    The verbs `event` applies to its pane, in order. `payload` is the event's JSON object, and
    `state` the pane's `core.State` as stored: `pane`, `role`, `turn` and decoded `pending`.
    A pane with no role counts as a lead and one with no turn as idle, so even `[]` registers
    an unknown pane.

`early(event, payload) -> list[core.Verb] | None`, optional
    Decides from the event alone, before the pane is read. `[]` drops the event, `[core.END]`
    ends the agent without a read, other verbs apply after the read, and None asks `verbs`.

The verbs, from `switchboard.core`:

    START           a new agent process: a lead, idle, with nothing pending and no task
    WORKING, IDLE   set the turn, keeping its task
    working(task)   set the turn working, with its task: the line of the prompt that started it
    DONE            set the turn done, or idle when a client views the session or the pane
                    is a teammate
    needs(key, reason)
                    add a pending prompt, keyed `lead` or by a subagent's id, with why it needs
                    the user; with no reason, the plain one
    resolve(key)    remove a pending prompt; RESOLVE_ALL removes every one
    TEAMMATE        mark the pane an agent-team teammate
    END             the agent has gone: unset every option

For example, an agent whose events are `begin`, `ask` and `finish`:

    from switchboard import core

    HANDLED = frozenset({"begin", "ask", "finish"})

    def verbs(event, payload, state):
        if event == "begin":
            return [core.START, core.WORKING]
        if event == "ask":
            return [core.needs("lead")]
        return [core.RESOLVE_ALL, core.DONE]
"""

from __future__ import annotations

import importlib
from types import ModuleType


def get(name: str) -> ModuleType | None:
    """The adapter for agent `name`, or None when there's none."""
    if not name.isidentifier() or name.startswith("_"):
        return None
    module = f"{__name__}.{name}"
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as error:
        if error.name != module:
            raise
        return None
