"""The two tmux reads, against the stub tmux."""

from __future__ import annotations

import sys

from switchboard import run, tmux
from switchboard.tmux import Pane, Session

SESSIONS_FORMAT = (
    "#{session_name}\t#{@wkt-worktree}\t#{session_path}\t#{session_last_attached}\t#{@attention}"
)
PANES_FORMAT = (
    "#{session_name}\t#{window_index}\t#{pane_id}\t#{pane_current_command}"
    "\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}\t#{@switchboard-at}"
    "\t#{@switchboard-agent}"
)


def test_sessions_is_one_list_sessions_query(stubs):
    stubs.tmux.answer(
        "list-sessions",
        stdout="widget/main\t/w/main\t/w/main\t1763500000\t\n"
        "scratch\t\t/tmp\t\t#[fg=themegreen]✓ widget/main#[default]\n"
        "bad line\n",
    )
    assert tmux.sessions() == [
        Session("widget/main", "/w/main", "/w/main", 1763500000),
        Session("scratch", "", "/tmp", 0, "#[fg=themegreen]✓ widget/main#[default]"),
    ]
    assert stubs.tmux.calls() == [["list-sessions", "-F", SESSIONS_FORMAT]]


def test_panes_is_one_list_panes_query(stubs):
    stubs.tmux.answer(
        "list-panes",
        stdout="a\t0\t%0\tclaude\tlead\tworking\tlead,a1\t1763500000\tclaude\n"
        "a\t1\t%1\tzsh\t\t\t\t\t\n"
        "b\t2\t%2\tpi\tlead\tidle\t\t\tpi\n"
        "b\t3\t%3\tclaude\tteammate\tidle\t\t\t\n",
    )
    panes = tmux.panes()
    assert panes == [
        Pane("a", 0, "%0", "claude", "lead", "working", ("lead", "a1"), 1763500000, "claude"),
        Pane("a", 1, "%1", "zsh"),
        Pane("b", 2, "%2", "pi", "lead", "idle", agent="pi"),
        Pane("b", 3, "%3", "claude", "teammate", "idle"),
    ]
    assert [(p.is_agent, p.state) for p in panes] == [
        (True, "needs"),
        (False, "idle"),
        (True, "idle"),
        (True, "idle"),
    ]
    assert stubs.tmux.calls() == [["list-panes", "-a", "-F", PANES_FORMAT]]


def test_an_unknown_role_is_not_an_agent():
    assert not Pane("a", 0, "%0", "zsh", "bogus", "working").is_agent


def test_agents_by_session_keeps_only_agents_in_pane_order():
    panes = tmux.parse_panes(
        "a\t0\t%0\tzsh\t\t\t\t\t\n"
        "a\t1\t%3\tclaude\tteammate\tdone\t\t\t\n"
        "b\t0\t%1\tclaude\tlead\tidle\t\t\t\n"
        "a\t2\t%2\tclaude\tlead\tworking\t\t\t\n"
    )
    found = tmux.agents_by_session(panes)
    assert {name: [p.id for p in agents] for name, agents in found.items()} == {
        "a": ["%3", "%2"],
        "b": ["%1"],
    }


def test_no_server_reads_nothing(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running on /tmp/tmux-0/default\n")
    assert tmux.sessions() == []
    assert tmux.panes() == []


def test_a_slow_command_gives_none(monkeypatch):
    monkeypatch.setattr(run, "TIMEOUT", 0.2)
    assert run.output(sys.executable, "-c", "import time; time.sleep(5)") is None
    assert run.output("/nonexistent/command") is None
    assert run.output(sys.executable, "-c", "print('ok')") == "ok\n"
