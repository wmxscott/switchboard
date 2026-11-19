"""Codex's adapter through `switchboard hook --agent codex`: Claude's mapping with Codex's
differences, and daemon-mode sessions dropped."""

from __future__ import annotations

import json
import os

import pytest

from switchboard import panestate

A1 = {"agent_id": "a1"}
ASK = {"tool_name": "request_user_input"}
DONE = [(client, "✓ work is done") for client in ("/dev/ttys001", "/dev/ttys002")]


@pytest.fixture
def codex(drive):
    return drive("codex", "hook_event_name")


MAPPING = [
    ("SessionStart", {"source": "startup"}, "::", "lead:idle:"),
    ("SessionStart", {"source": "startup"}, "lead:working:a1", "lead:idle:"),
    ("SessionStart", {"source": "resume"}, "lead:done:lead", "lead:idle:"),
    ("SessionStart", {"source": "clear"}, "::", "lead:idle:"),
    ("SessionStart", {"source": "compact"}, "lead:working:a1,lead", None),
    ("UserPromptSubmit", {}, "lead:done:a1,lead", "lead:working:"),
    ("UserPromptSubmit", A1, "lead:working:a1,lead", "lead:working:lead"),
    ("UserPromptSubmit", A1, "lead:done:a1", "lead:done:"),
    ("UserPromptSubmit", A1, "lead:idle:", None),
    ("PreToolUse", ASK, "lead:working:", "lead:working:lead"),
    ("PreToolUse", {**ASK, **A1}, "lead:working:lead", "lead:working:a1,lead"),
    ("PermissionRequest", {"tool_name": "shell"}, "lead:working:", "lead:working:lead"),
    ("PermissionRequest", A1, "lead:working:", "lead:working:a1"),
    ("PostToolUse", {}, "lead:working:lead", "lead:working:"),
    ("PostToolUse", {}, "lead:idle:", "lead:working:"),
    ("PostToolUse", A1, "lead:done:a1,a2", "lead:done:a2"),
    ("PostToolUse", {}, "lead:working:", None),
    ("Stop", {}, "lead:working:lead", "lead:done:"),
    ("Stop", {}, "lead:working:a1,lead", "lead:done:a1"),
    ("SubagentStop", A1, "lead:working:a1,lead", "lead:working:lead"),
    ("Interrupt", {}, "lead:working:lead", "lead:idle:"),
    ("Interrupt", {}, "lead:working:a1,lead", "lead:idle:a1"),
    ("Interrupt", {}, "lead:working:", "lead:idle:"),
    ("Interrupt", {}, "lead:idle:lead", "lead:idle:"),
    ("Interrupt", {}, "lead:done:", None),
]


@pytest.mark.parametrize(("event", "payload", "before", "expected"), MAPPING)
def test_event_mapping(codex, event, payload, before, expected):
    codex.stored(before)
    codex.fire(event, **payload)
    assert codex.after() == expected
    assert codex.calls()[0] == codex.read


def test_stop_in_a_session_a_client_is_viewing_goes_idle(codex):
    codex.stored("lead:working:", viewed=True)
    codex.fire("Stop")
    assert codex.after() == "lead:idle:"


@pytest.mark.parametrize("reason", ["other", "clear", "resume"])
def test_session_end_always_ends(codex, reason):
    codex.stored()
    codex.fire("SessionEnd", reason=reason)
    assert codex.written() == dict.fromkeys(panestate.OPTIONS)
    assert [call[0] for call in codex.calls()] == ["display-message", "set-option", "list-sessions"]


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("PreToolUse", {"tool_name": "shell"}),
        ("PreToolUse", {"tool_name": "AskUserQuestion"}),
        ("Notification", {"notification_type": "permission_prompt"}),
        ("TeammateIdle", {}),
        ("StopFailure", {}),
        ("PostToolUseFailure", {}),
        ("SubagentStart", A1),
        ("PreCompact", {}),
        ("PreModelRequest", {}),
    ],
)
def test_events_codex_does_not_track_never_call_tmux(codex, event, payload):
    codex.stored()
    codex.fire(event, **payload)
    assert codex.calls() == []


def test_a_subagents_prompt_submit_keeps_the_leads_prompt_turn_and_task(codex):
    codex.stored("lead:working:a1,lead", task="Add a --json flag")
    codex.fire("UserPromptSubmit", **SESSION, prompt="Explore the repo", **A1)
    assert codex.after() == "lead:working:lead"
    assert codex.task() == "Add a --json flag"
    assert codex.alerts() == []


SESSION = {
    "session_id": "019a3c5e-8f21-7d40-b3a9-5e2f1c7d9a04",
    "turn_id": "019a3c5f-0b12-7e31-a8c4-6f3d2e8b1c57",
    "transcript_path": "/Users/me/.codex/sessions/2026/11/19/rollout-019a3c5e.jsonl",
    "cwd": "/Users/me/src/app",
    "model": "gpt-5.5-codex",
    "permission_mode": "default",
}
QUESTIONS = [
    {
        "id": "database",
        "header": "Database",
        "question": "Which database should the app use?",
        "options": [
            {"label": "SQLite (Recommended)", "description": "One file, no server"},
            {"label": "Postgres", "description": "Shared with the API"},
        ],
    }
]


def tool(name: str, tool_input: object, **fields) -> dict:
    return {**SESSION, "tool_name": name, "tool_input": tool_input, **fields}


PATCH = "*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch\n"
REASONS = [
    ("PermissionRequest", tool("Bash", {"command": "npm test"}), "run: npm test"),
    ("PermissionRequest", tool("apply_patch", {"command": PATCH}), "apply_patch"),
    ("PermissionRequest", tool("mcp__github__get_issue", {"number": 7}), "mcp__github__get_issue"),
    ("PermissionRequest", tool("Bash", {}), ""),
    (
        "PreToolUse",
        tool("request_user_input", {"questions": QUESTIONS}, tool_use_id="call_7Hq2"),
        "asks: Which database should the app use?",
    ),
    ("PreToolUse", tool("request_user_input", {"questions": []}), ""),
    ("PreToolUse", tool("request_user_input", {"questions": [{"id": "db"}]}), ""),
    ("PreToolUse", tool("request_user_input", '{"questions": [oops'), ""),
    ("PreToolUse", {**SESSION, "tool_name": "request_user_input"}, ""),
]


@pytest.mark.parametrize(("event", "payload", "reason"), REASONS)
def test_each_prompt_gives_its_reason(codex, event, payload, reason):
    codex.stored("lead:working:")
    codex.fire(event, **payload)
    assert codex.after() == "lead:working:lead"
    assert codex.reasons() == {"lead": reason}


ID = SESSION["session_id"]
LEAD_EVENTS = [
    ("SessionStart", {"source": "startup"}, "::", "lead:idle:"),
    ("SessionStart", {"source": "clear"}, "lead:idle:", "lead:idle:"),
    ("UserPromptSubmit", {"prompt": "fix it"}, "lead:done:", "lead:working:"),
    ("PreToolUse", ASK, "lead:working:", "lead:working:lead"),
    ("PermissionRequest", {"tool_name": "shell"}, "lead:working:", "lead:working:lead"),
    ("PostToolUse", {}, "lead:working:", "lead:working:"),
    ("Stop", {}, "lead:working:", "lead:done:"),
    ("Interrupt", {}, "lead:working:", "lead:idle:"),
    ("Interrupt", {}, "lead:done:", "lead:done:"),
]


@pytest.mark.parametrize(("event", "payload", "before", "expected"), LEAD_EVENTS)
def test_the_leads_events_record_its_session_id(codex, event, payload, before, expected):
    codex.stored(before, session_id="019a0000-0000-7000-8000-000000000000")
    codex.fire(event, **SESSION, **payload)
    assert codex.after() == expected
    assert codex.written()[panestate.SESSION_ID] == ID


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("UserPromptSubmit", {"prompt": "Explore the repo"}),
        ("PreToolUse", ASK),
        ("PermissionRequest", {}),
        ("PostToolUse", {}),
        ("SubagentStop", {}),
    ],
)
def test_a_subagents_payload_never_writes_its_session_id(codex, event, payload):
    codex.stored("lead:working:a1,lead")
    codex.fire(event, **SESSION, **payload, **A1)
    assert (codex.written() or {}).get(panestate.SESSION_ID) is None


@pytest.mark.parametrize(
    ("text", "task"), [("Add a --json flag\n\nto the CLI", "Add a --json flag"), (None, "")]
)
def test_a_prompts_first_line_is_the_task_and_the_turn_done_keeps_it(codex, text, task):
    codex.stored("lead:done:")
    codex.fire("UserPromptSubmit", **SESSION, prompt=text)
    assert (codex.after(), codex.task()) == ("lead:working:", task)
    codex.stubs.tmux.log_path.unlink()
    codex.stored("lead:working:", task=task)
    codex.fire("Stop", **SESSION, stop_hook_active=False, last_assistant_message="Done.")
    assert (codex.after(), codex.task()) == ("lead:done:", task)


def test_an_interrupt_with_a_prompt_pending_goes_idle_without_an_alert(codex):
    codex.stored("lead:working:lead")
    codex.fire("Interrupt")
    assert codex.after() == "lead:idle:"
    assert codex.alerts() == []
    assert codex.calls()[-1][0] == "list-sessions"


def test_needs_you_and_done_alert(codex):
    codex.stored("lead:working:")
    codex.fire("PermissionRequest")
    assert codex.alerts()[0] == ("/dev/ttys001", "▲ work needs you")
    codex.stubs.tmux.log_path.unlink()
    codex.fire("Stop")
    assert codex.alerts() == DONE


@pytest.mark.parametrize(
    ("event", "payload"),
    [("PermissionRequest", {}), ("Stop", {}), ("Interrupt", {}), ("SessionEnd", {})],
)
def test_a_daemon_mode_session_is_dropped(codex, ps, event, payload):
    """The daemon's hooks carry the `$TMUX_PANE` of the TUI that started it, not their own."""
    codex.stored("lead:working:", inside=False)
    codex.fire(event, **payload)
    assert codex.calls() == [codex.read]
    assert ps.calls() == ["-axo pid=,ppid="]


def test_a_claude_team_config_never_makes_a_codex_pane_a_teammate(codex, tmp_path):
    config = tmp_path / "home" / ".claude" / "teams" / "session-1" / "config.json"
    config.parent.mkdir(parents=True)
    members = [{"name": "researcher", "tmuxPaneId": codex.pane}]
    config.write_text(json.dumps({"leadProcess": {"pid": os.getpid()}, "members": members}))
    codex.stored("::")
    codex.fire("Stop")
    assert codex.after() == "lead:done:"
