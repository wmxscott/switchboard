"""`switchboard hook <event>`: an agent's hook event, with its JSON payload on stdin, goes
through the agent's adapter to its pane's state."""

from __future__ import annotations

import json

from switchboard import agents, core

AGENT = "claude"


def handle(args: list[str], pane: str, stdin: bytes) -> None:
    adapter = agents.get(AGENT)
    if adapter is None:
        return
    payload = json.loads(stdin)
    if not isinstance(payload, dict):
        return
    event = args[0] if args else str(payload.get("hook_event_name", ""))
    core.handle(adapter, event, payload, pane)
