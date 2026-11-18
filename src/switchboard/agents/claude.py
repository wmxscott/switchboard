"""Claude Code: its hook events, with agent-team teammates found through the team config."""

from __future__ import annotations

import json
import os

from switchboard import core
from switchboard import panestate as ps

NEEDS_NOTICES = frozenset({"permission_prompt", "elicitation_dialog", "elicitation_url_dialog"})
INTERACTIVE_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})
TOOL_DONE = frozenset({"PostToolUse", "PostToolUseFailure"})
TURN_END = frozenset({"Stop", "StopFailure", "TeammateIdle"})
HANDLED = (
    TOOL_DONE
    | TURN_END
    | {"UserPromptSubmit", "PermissionRequest", "SubagentStop", "SessionStart", "SessionEnd"}
    | {"PreToolUse", "Notification"}
)
SESSION_KEPT = frozenset({"clear", "resume"})
NEW_CLAUDE = frozenset({"startup", "resume"})


def early(event: str, payload: dict) -> list[core.Verb] | None:
    if event == "SessionEnd" and payload.get("reason") not in SESSION_KEPT:
        return [core.END]
    if event == "PreToolUse":
        return None if payload.get("tool_name") in INTERACTIVE_TOOLS else []
    if event == "Notification":
        kind = payload.get("notification_type")
        return None if kind == "idle_prompt" or kind in NEEDS_NOTICES else []
    return None


def verbs(event: str, payload: dict, state: core.State) -> list[core.Verb]:
    fresh = event == "SessionStart" and payload.get("source") in NEW_CLAUDE
    key = _key(payload)
    found = [core.START] if fresh else []
    if _teammate(event, key, "" if fresh else state.role, state.pane):
        found.append(core.TEAMMATE)
    if event == "UserPromptSubmit":
        # Only a typed prompt shows that no other agent's dialog is still open.
        typed = payload.get("source", "user") == "user"
        found += [core.WORKING, core.RESOLVE_ALL if typed else core.resolve(ps.LEAD_KEY)]
    elif event in ("PermissionRequest", "PreToolUse"):
        found.append(core.needs(key))
    elif event == "Notification":
        if payload.get("notification_type") == "idle_prompt":
            found += [core.IDLE] if state.turn == ps.WORKING else []
        elif not state.pending:
            # Names no agent, and repeats a PermissionRequest seconds later.
            found.append(core.needs(key))
    elif event in TOOL_DONE:
        found.append(core.resolve(key))
        found += [core.WORKING] if key == ps.LEAD_KEY else []
    elif event == "SubagentStop" or (event in TURN_END and key != ps.LEAD_KEY):
        found.append(core.resolve(key))
    elif event in TURN_END:
        found += [core.resolve(ps.LEAD_KEY), core.DONE]
    elif event == "SessionEnd":
        found += [core.IDLE, core.RESOLVE_ALL]
    return found


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


def _teammate(event: str, key: str, stored: str, pane: str) -> bool:
    if event == "TeammateIdle" and key == ps.LEAD_KEY:
        return True
    return stored not in ps.ROLES and listed_as_teammate(pane)


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
