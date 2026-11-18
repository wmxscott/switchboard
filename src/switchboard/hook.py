"""`switchboard hook <event>`: a Claude Code hook event becomes its pane's agent state.

At most one tmux read and one tmux write per event, and only light imports.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable

from switchboard import panestate as ps
from switchboard import run

NEEDS_NOTICES = frozenset({"permission_prompt", "elicitation_dialog", "elicitation_url_dialog"})
INTERACTIVE_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})
TOOL_DONE = frozenset({"PostToolUse", "PostToolUseFailure"})
TURN_END = frozenset({"Stop", "StopFailure", "TeammateIdle"})
HANDLED = (
    TOOL_DONE | TURN_END | {"UserPromptSubmit", "PermissionRequest", "SubagentStop", "SessionEnd"}
)
SESSION_KEPT = frozenset({"clear", "resume"})
PANE_FORMAT = "\t".join(f"#{{{name}}}" for name in ("session_name", ps.ROLE, ps.TURN, ps.PENDING))
CLIENT_SESSIONS = ("list-clients", "-F", "#{client_session}")

State = tuple[str, str, str]


def handle(args: list[str], pane: str, stdin: bytes) -> None:
    payload = json.loads(stdin)
    if not isinstance(payload, dict):
        return
    event = args[0] if args else str(payload.get("hook_event_name", ""))
    if event == "SessionEnd" and payload.get("reason") not in SESSION_KEPT:
        run.output("tmux", *_chain(("set-option", "-p", "-u", "-t", pane, o) for o in ps.OPTIONS))
        return
    if not _relevant(event, payload):
        return
    view = read(pane)
    if view is None:
        return
    session, stored, viewed = view
    state = apply(event, payload, pane, stored, viewed)
    if state != stored:
        write(pane, state)
        changed(session, stored, state)


def changed(session: str, before: State, after: State) -> None:
    """Called after every state change: A4 refreshes `@attention` and alerts here."""


def apply(event: str, payload: dict, pane: str, stored: State, viewed: bool) -> State:
    """The new (role, turn, pending) of `pane`, whose options hold `stored`."""
    stored_role, stored_turn, stored_pending = stored
    key = _key(payload)
    role = _role(event, key, stored_role, pane)
    turn = stored_turn if stored_turn in ps.TURNS else ps.IDLE
    keys = set(ps.decode_pending(stored_pending))
    if event == "UserPromptSubmit":
        turn = ps.WORKING
        # Only a typed prompt shows that no other agent's dialog is still open.
        keys = set() if payload.get("source", "user") == "user" else keys - {ps.LEAD_KEY}
    elif event in ("PermissionRequest", "PreToolUse"):
        keys.add(key)
    elif event == "Notification":
        if payload.get("notification_type") == "idle_prompt":
            turn = ps.IDLE if turn == ps.WORKING else turn
        elif not keys:
            # Names no agent, and repeats a PermissionRequest seconds later.
            keys.add(key)
    elif event in TOOL_DONE:
        keys.discard(key)
        turn = ps.WORKING if key == ps.LEAD_KEY else turn
    elif event == "SubagentStop" or (event in TURN_END and key != ps.LEAD_KEY):
        keys.discard(key)
    elif event in TURN_END:
        keys.discard(ps.LEAD_KEY)
        turn = ps.IDLE if role == ps.TEAMMATE or viewed else ps.DONE
    elif event == "SessionEnd":
        keys.clear()
        turn = ps.IDLE
    return role, turn, ps.encode_pending(keys)


def read(pane: str) -> tuple[str, State, bool] | None:
    """The pane's session, its stored state, and whether a client is viewing that session."""
    out = run.output(
        "tmux", *_chain([("display-message", "-p", "-t", pane, PANE_FORMAT), CLIENT_SESSIONS])
    )
    if out is None:
        return None
    first, *clients = out.split("\n")
    fields = first.split("\t")
    if len(fields) != 4:
        return None
    session, role, turn, pending = fields
    return session, (role, turn, pending), session in clients


def write(pane: str, state: State) -> None:
    role, turn, pending = state
    commands = [
        ("set-option", "-p", "-t", pane, ps.ROLE, role),
        ("set-option", "-p", "-t", pane, ps.TURN, turn),
        ("set-option", "-p", "-t", pane, ps.AT, str(int(time.time()))),
        ("set-option", "-p", "-t", pane, ps.PENDING, pending)
        if pending
        else ("set-option", "-p", "-u", "-t", pane, ps.PENDING),
    ]
    run.output("tmux", *_chain(commands))


def listed_as_teammate(pane: str) -> bool:
    """Whether a live Claude Code team config lists `pane` as a member's tmux pane.

    The lead's member entry holds `leader`, never a pane id.
    """
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    teams = os.path.join(root, "teams")
    try:
        names = os.listdir(teams)
    except OSError:
        return False
    for name in names:
        try:
            with open(os.path.join(teams, name, "config.json"), encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, ValueError):
            continue
        members = config.get("members") if isinstance(config, dict) else None
        if not isinstance(members, list) or not _alive(config.get("leadProcess")):
            continue
        if any(isinstance(m, dict) and m.get("tmuxPaneId") == pane for m in members):
            return True
    return False


def _role(event: str, key: str, stored: str, pane: str) -> str:
    if stored == ps.TEAMMATE or (event == "TeammateIdle" and key == ps.LEAD_KEY):
        return ps.TEAMMATE
    if stored == ps.LEAD or not listed_as_teammate(pane):
        return ps.LEAD
    return ps.TEAMMATE


def _relevant(event: str, payload: dict) -> bool:
    if event == "PreToolUse":
        return payload.get("tool_name") in INTERACTIVE_TOOLS
    if event == "Notification":
        kind = payload.get("notification_type")
        return kind == "idle_prompt" or kind in NEEDS_NOTICES
    return event in HANDLED


def _key(payload: dict) -> str:
    agent = payload.get("agent_id")
    return (isinstance(agent, str) and ps.encode_pending([agent])) or ps.LEAD_KEY


def _alive(lead: object) -> bool:
    pid = lead.get("pid") if isinstance(lead, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _chain(commands: Iterable[tuple[str, ...]]) -> list[str]:
    args: list[str] = []
    for command in commands:
        args += [";", *command] if args else command
    return args
