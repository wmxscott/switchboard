"""Codex: its hooks take Claude Code's event names and payloads, so this is Claude's mapping with
Codex's differences. Codex has no agent teams, and its `UserPromptSubmit` has no `source`.

Only a session started with `codex --no-daemon` runs its hooks inside its pane. The daemon's
hooks carry another pane's `$TMUX_PANE`, so the pane guard drops them.
"""

from __future__ import annotations

from switchboard import core
from switchboard import panestate as ps
from switchboard.agents import claude

INTERACTIVE_TOOLS = frozenset({"request_user_input"})
HANDLED = frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "Stop",
        "SubagentStop",
        "Interrupt",
        "SessionEnd",
    }
)


def early(event: str, payload: dict) -> list[core.Verb] | None:
    if event == "SessionEnd":
        return [core.END]
    if event == "PreToolUse":
        return None if payload.get("tool_name") in INTERACTIVE_TOOLS else []
    return None


def verbs(event: str, payload: dict, state: core.State) -> list[core.Verb]:
    agent = claude.key(payload)
    if event == "Interrupt":
        idle = [core.IDLE] if state.turn == ps.WORKING else []
        return [*claude.session(payload), core.resolve(ps.LEAD_KEY), *idle]
    if event == "UserPromptSubmit" and agent != ps.LEAD_KEY:
        # A subagent got its task: no one typed anything.
        return [core.resolve(agent)]
    if event == "PreToolUse":
        return [*claude.session(payload), core.needs(agent, claude.asks(payload))]
    return claude.verbs(event, payload, state, teams=False)
