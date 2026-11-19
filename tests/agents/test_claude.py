"""Claude Code's adapter through `switchboard hook <event>` against the stub tmux: the event
mapping, teammates, and failures.

A pane's state is written `role:turn:pending` here, as in `lead:working:a1,lead`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from switchboard import alert, hook, panestate
from switchboard.agents import claude

PANE = "%7"
READ = [
    *("display-message", "-p", "-t", PANE),
    "#{session_name}\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}",
    *(";", "list-clients", "-F", "#{client_name}\t#{client_session}"),
]
SCRIPT = os.path.join(os.path.dirname(sys.executable), "switchboard")
A1 = {"agent_id": "a1"}


def stored(stubs, state: str = "lead:working:", viewed: bool = False) -> None:
    """What the stub tmux answers the hook's read with: the pane is in `work`, and two clients
    are elsewhere, or one of them is on `work` when `viewed`."""
    lines = [
        "work\t" + state.replace(":", "\t"),
        "/dev/ttys001\t" + ("work" if viewed else "elsewhere"),
        "/dev/ttys002\tother",
    ]
    stubs.tmux.answer("display-message", stdout="\n".join(lines) + "\n")


def fire(event: str, **payload) -> None:
    hook.handle([event], PANE, json.dumps({"session_id": "s", **payload}).encode())


def note(kind: str) -> dict:
    return {"notification_type": kind}


def commands(call: list[str]) -> list[list[str]]:
    found: list[list[str]] = [[]]
    for arg in call:
        if arg == ";":
            found.append([])
        else:
            found[-1].append(arg)
    return found


def written(stubs) -> dict[str, str | None] | None:
    """The options the single write set, None for each it unset; None when nothing was written."""
    writes = [call for call in stubs.tmux.calls() if call[0] == "set-option"]
    assert len(writes) <= 1
    if not writes:
        return None
    options: dict[str, str | None] = {}
    for command in commands(writes[0]):
        assert command[:2] == ["set-option", "-p"]
        if command[2] == "-u":
            assert command[3:5] == ["-t", PANE]
            options[command[5]] = None
        else:
            assert command[2:4] == ["-t", PANE]
            options[command[4]] = command[5]
    return options


def after(stubs) -> str | None:
    options = written(stubs)
    if options is None:
        return None
    assert abs(int(options["@switchboard-at"]) - time.time()) < 60
    names = ("@switchboard-role", "@switchboard-turn", "@switchboard-pending")
    return ":".join(options[name] or "" for name in names)


MAPPING = [
    ("UserPromptSubmit", {}, "lead:done:a1,lead", "lead:working:"),
    ("UserPromptSubmit", {"source": "user"}, "lead:idle:a1", "lead:working:"),
    ("UserPromptSubmit", {"source": "system"}, "lead:done:a1,lead", "lead:working:a1"),
    ("UserPromptSubmit", {}, "::", "lead:working:"),
    ("PermissionRequest", {}, "lead:working:", "lead:working:lead"),
    ("PermissionRequest", A1, "lead:working:lead", "lead:working:a1,lead"),
    ("PreToolUse", {"tool_name": "AskUserQuestion", **A1}, "lead:working:", "lead:working:a1"),
    ("PreToolUse", {"tool_name": "ExitPlanMode"}, "lead:working:", "lead:working:lead"),
    ("Notification", note("permission_prompt"), "lead:working:", "lead:working:lead"),
    ("Notification", note("elicitation_dialog"), "lead:working:", "lead:working:lead"),
    ("Notification", note("elicitation_url_dialog"), "lead:working:", "lead:working:lead"),
    ("Notification", note("permission_prompt"), "lead:working:a1", None),
    ("PostToolUse", {}, "lead:working:a1,lead", "lead:working:a1"),
    ("PostToolUseFailure", {}, "lead:working:lead", "lead:working:"),
    ("PostToolUse", {}, "lead:idle:", "lead:working:"),
    ("PostToolUse", {}, "lead:done:", "lead:working:"),
    ("PostToolUse", A1, "lead:done:a1,a2", "lead:done:a2"),
    ("PostToolUse", {}, "lead:working:", None),
    ("SubagentStop", A1, "lead:working:a1,a2,lead", "lead:working:a2,lead"),
    ("Stop", {}, "lead:working:lead", "lead:done:"),
    ("StopFailure", {"error": "rate_limit"}, "lead:working:", "lead:done:"),
    ("Stop", {}, "teammate:working:", "teammate:idle:"),
    ("Notification", note("idle_prompt"), "lead:working:", "lead:idle:"),
    ("Notification", note("idle_prompt"), "lead:done:", None),
    ("TeammateIdle", {"teammate_name": "researcher"}, "lead:working:", "teammate:idle:"),
    ("TeammateIdle", A1, "lead:working:a1", "lead:working:"),
    ("SessionEnd", {"reason": "clear"}, "lead:done:a1,lead", "lead:idle:"),
    ("SessionEnd", {"reason": "resume"}, "teammate:working:lead", "teammate:idle:"),
    ("SessionStart", {"source": "startup"}, "::", "lead:idle:"),
    ("SessionStart", {"source": "startup"}, "lead:working:a1", "lead:idle:"),
    ("SessionStart", {"source": "resume"}, "lead:working:a1", "lead:idle:"),
    ("SessionStart", {"source": "resume"}, "lead:done:", "lead:idle:"),
    ("SessionStart", {"source": "startup"}, "teammate:working:", "lead:idle:"),
    ("SessionStart", {"source": "compact"}, "lead:working:a1,lead", None),
    ("SessionStart", {"source": "fork"}, "lead:working:a1,lead", None),
    ("SessionStart", {"source": "clear"}, "lead:idle:", None),
    ("SessionStart", {"source": "clear"}, "teammate:done:", None),
]


@pytest.mark.parametrize(("event", "payload", "before", "expected"), MAPPING)
def test_event_mapping(stubs, event, payload, before, expected):
    stored(stubs, before)
    fire(event, hook_event_name=event, **payload)
    assert after(stubs) == expected
    assert stubs.tmux.calls()[0] == READ


def test_stop_in_a_session_a_client_is_viewing_goes_idle(stubs):
    stored(stubs, "lead:working:lead", viewed=True)
    fire("Stop")
    assert after(stubs) == "lead:idle:"


def test_the_leads_stop_keeps_a_background_subagents_prompt(stubs):
    stored(stubs, "lead:working:a1,lead")
    fire("Stop")
    assert after(stubs) == "lead:done:a1"


def test_idle_prompt_after_an_interrupt_clears_working(stubs):
    stored(stubs, "lead:working:")
    fire("Notification", message="Claude is waiting for your input", **note("idle_prompt"))
    assert after(stubs) == "lead:idle:"


def test_parallel_subagents_do_not_clear_each_other(stubs):
    steps = [
        ("PermissionRequest", "a1", "lead:working:", "lead:working:a1"),
        ("PermissionRequest", "a2", "lead:working:a1", "lead:working:a1,a2"),
        ("PostToolUse", "a2", "lead:working:a1,a2", "lead:working:a1"),
        ("SubagentStop", "a3", "lead:working:a1", None),
        ("PostToolUse", "a1", "lead:working:a1", "lead:working:"),
    ]
    for event, agent, before, expected in steps:
        stubs.tmux.log_path.unlink(missing_ok=True)
        stored(stubs, before)
        fire(event, agent_id=agent)
        assert after(stubs) == expected, (event, agent)


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact", "fork"])
def test_a_session_start_registers_a_fresh_pane_as_an_idle_lead(stubs, source):
    stored(stubs, "::")
    fire("SessionStart", hook_event_name="SessionStart", source=source)
    assert after(stubs) == "lead:idle:"


@pytest.mark.parametrize("source", ["startup", "resume"])
def test_a_new_claude_resets_a_stale_pane(stubs, source):
    stored(stubs, "lead:working:a1")
    fire("SessionStart", hook_event_name="SessionStart", source=source)
    assert after(stubs) == "lead:idle:"


@pytest.mark.parametrize("source", ["compact", "fork"])
def test_a_mid_session_start_leaves_a_working_agent_and_its_prompts_alone(stubs, source):
    stored(stubs, "lead:working:a1,lead")
    fire("SessionStart", hook_event_name="SessionStart", source=source)
    assert stubs.tmux.calls() == [READ]


def test_session_end_unsets_every_option_without_reading_then_refreshes(stubs):
    fire("SessionEnd", reason="prompt_input_exit")
    assert [call[0] for call in stubs.tmux.calls()] == ["set-option", "list-sessions"]
    assert written(stubs) == dict.fromkeys(panestate.OPTIONS)


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("PreToolUse", {"tool_name": "Bash"}),
        ("Notification", note("agent_needs_input")),
        ("Notification", note("agent_completed")),
        ("Notification", note("auth_success")),
        ("SubagentStart", A1),
        ("PostToolBatch", {}),
        ("NoSuchEvent", {}),
    ],
)
def test_events_that_change_nothing_never_call_tmux(stubs, event, payload):
    stored(stubs)
    fire(event, **payload)
    assert stubs.tmux.calls() == []


def test_the_payload_names_the_event_without_an_argument(stubs):
    stored(stubs)
    hook.handle([], PANE, json.dumps({"hook_event_name": "PermissionRequest"}).encode())
    assert after(stubs) == "lead:working:lead"


@pytest.mark.parametrize("answer", [{"code": 1}, {"stdout": "not\tenough\n"}])
def test_a_failed_read_writes_nothing(stubs, answer):
    stubs.tmux.answer("display-message", **answer)
    fire("Stop")
    assert stubs.tmux.calls() == [READ]


@pytest.fixture
def team(tmp_path):
    """Writes a Claude Code team config listing `pane` as a teammate's, under `home`."""

    def write(pane: str = PANE, pid: int | None = None, home=tmp_path / "home") -> None:
        config = home / ".claude" / "teams" / "session-1a2b3c4d" / "config.json"
        config.parent.mkdir(parents=True)
        members = [
            {"agentId": "team-lead@s", "agentType": "team-lead", "tmuxPaneId": "leader"},
            {"agentId": "researcher@s", "name": "researcher", "tmuxPaneId": pane},
        ]
        lead = {"pid": os.getpid() if pid is None else pid}
        config.write_text(json.dumps({"leadProcess": lead, "members": members}))

    return write


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_a_pane_in_a_team_config_is_a_teammate_from_its_first_event(stubs, team):
    team()
    stored(stubs, "::")
    fire("UserPromptSubmit", prompt="hi")
    assert after(stubs) == "teammate:working:"


@pytest.mark.parametrize("before", ["::", "teammate:working:a1", "lead:working:a1"])
def test_a_pane_in_a_team_config_starts_as_an_idle_teammate(stubs, team, before):
    team()
    stored(stubs, before)
    fire("SessionStart", source="startup")
    assert after(stubs) == "teammate:idle:"


def test_a_teammates_stop_goes_idle_not_done(stubs, team):
    team()
    stored(stubs, ":working:")
    fire("Stop")
    assert after(stubs) == "teammate:idle:"


def test_a_teammate_still_raises_needs_you(stubs, team):
    team()
    stored(stubs, ":working:")
    fire("PermissionRequest", tool_name="Bash")
    assert after(stubs) == "teammate:working:lead"


@pytest.mark.parametrize("which", ["other pane", "dead lead"])
def test_other_panes_and_dead_teams_are_not_teammates(stubs, team, which):
    if which == "other pane":
        team(pane="%99")
    else:
        team(pid=dead_pid())
    stored(stubs, ":working:")
    fire("Stop")
    assert after(stubs) == "lead:done:"


def test_a_stored_role_is_kept(stubs, team):
    team()
    stored(stubs, "lead:working:")
    fire("Stop")
    assert after(stubs) == "lead:done:"


def test_the_team_configs_follow_claude_config_dir(stubs, team, tmp_path, monkeypatch):
    team(home=tmp_path / "elsewhere")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere" / ".claude"))
    stored(stubs, ":working:")
    fire("Stop")
    assert after(stubs) == "teammate:idle:"


@pytest.mark.parametrize("content", ["not json", "[]", '{"members": 3}', '{"members": [3]}'])
def test_a_broken_team_config_is_skipped(tmp_path, content):
    config = tmp_path / "home" / ".claude" / "teams" / "broken" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(content)
    assert not claude.listed_as_teammate(PANE)


def script(event: str, payload: str):
    return subprocess.run(
        [SCRIPT, "hook", event],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "TMUX_PANE": PANE},
    )


@pytest.mark.parametrize("event", ["Stop", "SessionStart"])
@pytest.mark.parametrize("payload", ["", "not json {", "{", "[1, 2]", '"Stop"'])
def test_a_malformed_payload_exits_0_silently(stubs, event, payload):
    stored(stubs)
    result = script(event, payload)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls() == []


PATIENT = "import sys; from switchboard import cli, run; run.TIMEOUT = 60; sys.exit(cli.main())"


def test_a_failing_tmux_exits_0_silently(stubs):
    """Through `cli.main` with a long tmux timeout: under the usual 2 seconds, a stub slow to start
    is killed before it logs the read."""
    stubs.tmux.answer("*", code=1, stderr="no server running\n")
    result = subprocess.run(
        [sys.executable, "-c", PATIENT, "hook", "PermissionRequest"],
        input="{}",
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "TMUX_PANE": PANE},
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls() == [READ]


def test_the_console_script_writes_the_state(stubs):
    stored(stubs)
    result = script("PermissionRequest", json.dumps({"hook_event_name": "PermissionRequest"}))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert after(stubs) == "lead:working:lead"


def test_a_session_start_prints_nothing_for_claude_to_read(stubs):
    """Claude Code adds a SessionStart hook's stdout to the session's context."""
    stored(stubs, "::")
    result = script("SessionStart", json.dumps({"hook_event_name": "SessionStart"}))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert after(stubs) == "lead:idle:"


@pytest.fixture
def played(monkeypatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(alert, "play", lambda: calls.append(True))
    return calls


def alerts(stubs) -> list[tuple[str, str]]:
    """Each client the hook messaged, with the message."""
    found = []
    for call in stubs.tmux.calls():
        for command in commands(call):
            if command[:2] == ["display-message", "-c"]:
                assert command[3:5] == ["-d", "4000"]
                found.append((command[2], command[5]))
    return found


def test_a_change_to_needs_you_alerts_every_client_once_then_refreshes(stubs, played):
    stored(stubs, "lead:working:")
    fire("PermissionRequest")
    message = "▲ work needs you"
    assert alerts(stubs) == [("/dev/ttys001", message), ("/dev/ttys002", message)]
    assert played == [True]
    assert [call[0] for call in stubs.tmux.calls()] == [
        "display-message",
        "set-option",
        "display-message",
        "list-sessions",
    ]


def test_no_alert_for_a_session_a_client_is_viewing(stubs, played):
    stored(stubs, "lead:working:", viewed=True)
    fire("PermissionRequest")
    assert after(stubs) == "lead:working:lead"
    assert alerts(stubs) == []
    assert played == []
    assert stubs.tmux.calls()[-1][0] == "list-sessions"


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        ("lead:working:", [(c, "✓ work is done") for c in ("/dev/ttys001", "/dev/ttys002")]),
        ("teammate:working:", []),
    ],
)
def test_a_leads_done_alerts_but_a_teammates_stop_does_not(stubs, played, before, expected):
    stored(stubs, before)
    fire("Stop")
    assert alerts(stubs) == expected
    assert played == ([True] if expected else [])


def test_a_teammates_needs_you_alerts(stubs, played):
    stored(stubs, "teammate:working:")
    fire("PermissionRequest", tool_name="Bash")
    assert alerts(stubs)[0] == ("/dev/ttys001", "▲ work needs you")


def test_a_leads_stop_with_a_prompt_pending_does_not_alert(stubs, played):
    stored(stubs, "lead:working:a1")
    fire("Stop")
    assert after(stubs) == "lead:done:a1"
    assert alerts(stubs) == []
    assert played == []
    assert stubs.tmux.calls()[-1][0] == "list-sessions"


@pytest.mark.parametrize(
    ("viewed", "expected"),
    [
        (False, [(c, "✓ work is done") for c in ("/dev/ttys001", "/dev/ttys002")]),
        (True, []),
    ],
)
def test_answering_that_prompt_alerts_done_unless_viewed(stubs, played, viewed, expected):
    stored(stubs, "lead:done:a1", viewed=viewed)
    fire("PostToolUse", agent_id="a1")
    assert after(stubs) == "lead:done:"
    assert alerts(stubs) == expected
    assert played == ([True] if expected else [])


@pytest.mark.parametrize(
    ("source", "before"),
    [
        ("startup", "::"),
        ("startup", "lead:working:a1"),
        ("resume", "lead:done:lead"),
        ("compact", "::"),
        ("clear", "::"),
        ("fork", "::"),
    ],
)
def test_a_session_start_never_alerts(stubs, played, source, before):
    stored(stubs, before)
    fire("SessionStart", source=source)
    assert after(stubs) == "lead:idle:"
    assert alerts(stubs) == []
    assert played == []
    assert [call[0] for call in stubs.tmux.calls()] == [
        "display-message",
        "set-option",
        "list-sessions",
    ]


def test_another_prompt_while_one_is_pending_does_not_alert_again(stubs, played):
    stored(stubs, "lead:working:a1")
    fire("PermissionRequest")
    assert after(stubs) == "lead:working:a1,lead"
    assert alerts(stubs) == []
    assert played == []


def test_a_change_without_news_only_refreshes(stubs, played):
    stored(stubs, "lead:working:lead")
    fire("PostToolUse")
    assert after(stubs) == "lead:working:"
    assert alerts(stubs) == []
    assert stubs.tmux.calls()[-1][0] == "list-sessions"


def test_no_change_neither_alerts_nor_refreshes(stubs, played):
    stored(stubs, "lead:working:")
    fire("PostToolUse")
    assert stubs.tmux.calls() == [READ]
    assert played == []


def test_the_refresh_after_a_change_updates_other_sessions(stubs, played):
    stored(stubs, "lead:working:")
    stubs.tmux.answer("list-sessions", stdout="work\t\t/w\t0\t\nother\t\t/o\t0\t\n")
    stubs.tmux.answer(
        "list-panes", stdout="work\t0\t0\t%7\tclaude\tlead\tworking\tlead\t0\tclaude\t\n"
    )
    fire("PermissionRequest")
    writes = [call for call in stubs.tmux.calls() if "@attention" in call]
    assert writes == [
        ["set-option", "-t", "=other:", "@attention", "#[fg=themered]▲ work#[default] "]
    ]


def test_the_hook_does_not_wait_for_the_sound(stubs, tmp_path):
    started = tmp_path / "started"
    slow = tmp_path / "bin" / "afplay"
    slow.write_text(
        f"#!{sys.executable}\nimport sys, time\n"
        f"open({str(started)!r}, 'w').write(sys.argv[1])\ntime.sleep(5)\n"
    )
    stored(stubs, "lead:working:")
    payload = json.dumps({"hook_event_name": "PermissionRequest"})
    start = time.perf_counter()
    result = subprocess.run(
        [SCRIPT, "hook", "PermissionRequest"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "TMUX_PANE": PANE, "SWITCHBOARD_SOUND": "/sounds/chime.aiff"},
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert time.perf_counter() - start < 3
    assert alerts(stubs)
    deadline = time.monotonic() + 10
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert started.read_text() == "/sounds/chime.aiff"


RUNS = 15
BAR = 0.15


def test_a_tool_event_with_nothing_pending_stays_fast(stubs):
    """The median wall time of one read and no write, including the stub tmux's own start."""
    stored(stubs)
    payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Read"})
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        result = script("PostToolUse", payload)
        times.append(time.perf_counter() - start)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls() == [READ] * RUNS
    assert sorted(times)[RUNS // 2] < BAR
