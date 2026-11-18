"""Pi: the events the ai-toolkit extension forwards, each with its fields on stdin.

A dialog pends as `ui`, however many are nested, and a Plannotator session by its id.
"""

from __future__ import annotations

from switchboard import core

UI = "ui"
PLANNOTATOR = frozenset({"plannotator_opened", "plannotator_closed"})
HANDLED = PLANNOTATOR | {
    "session_start",
    "agent_start",
    "ui_prompt_start",
    "ui_prompt_end",
    "agent_settled",
    "session_shutdown",
}


def early(event: str, payload: dict) -> list[core.Verb] | None:
    if event == "session_shutdown":
        return [core.END] if payload.get("reason") == "quit" else []
    if event in PLANNOTATOR and not _id(payload):
        return []
    return None


def verbs(event: str, payload: dict, state: core.State) -> list[core.Verb]:
    match event:
        case "session_start":
            return [core.START, *([core.WORKING] if payload.get("idle") is False else [])]
        case "agent_start":
            return [core.WORKING]
        case "ui_prompt_start":
            return [core.needs(UI)]
        case "ui_prompt_end":
            return [core.resolve(UI)]
        case "plannotator_opened":
            return [core.needs(_id(payload))]
        case "plannotator_closed":
            return [core.resolve(_id(payload))]
        case "agent_settled" if payload.get("aborted"):
            return [core.IDLE]
        case "agent_settled":
            return [core.DONE, core.RESOLVE_ALL]
    return []


def _id(payload: dict) -> str:
    found = payload.get("id")
    return found if isinstance(found, str) else ""
