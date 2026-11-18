"""`switchboard hook [--agent NAME] <event>`: an agent's hook event, with its JSON payload on
stdin, goes through the agent's adapter to its pane's state. The agent is Claude by default."""

from __future__ import annotations

import json

from switchboard import agents, core


def handle(args: list[str], pane: str, stdin: bytes) -> None:
    found = core.split_agent(args)
    adapter = agents.get(found[0]) if found else None
    if found is None or adapter is None:
        return
    agent, rest = found
    payload = json.loads(stdin)
    if not isinstance(payload, dict):
        return
    event = rest[0] if rest else str(payload.get("hook_event_name", ""))
    core.handle(adapter, event, payload, pane, agent)
