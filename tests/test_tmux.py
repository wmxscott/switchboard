"""The two tmux reads, against the stub tmux."""

from __future__ import annotations

import itertools
import sys

import pytest

from switchboard import run, tmux
from switchboard.tmux import Pane, Session

SESSIONS_FORMAT = (
    "#{session_name}\t#{@wkt-worktree}\t#{session_path}\t#{session_last_attached}\t#{@attention}"
)
PANES_FORMAT = (
    "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_current_command}"
    "\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}\t#{@switchboard-at}"
    "\t#{@switchboard-agent}\t#{@switchboard-reasons}\t#{@switchboard-task}"
    "\t#{@switchboard-card-at}\t#{@switchboard-session-id}\t#{@switchboard-sidebar}"
)
ID = "3f1c9e2a-7b4d-4e0a-9c1f-2d8e6b5a4c3d"


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
        stdout="a\t0\t0\t%0\tclaude\tlead\tworking\tlead,a1\t1763500000\tclaude"
        f'\t{{"lead":"run: ls","a1":""}}\t"fix it; now"\t1763499000\t{ID}\t\n'
        "a\t1\t0\t%1\tzsh\t\t\t\t\t\t\t\t\t\t\n"
        "b\t2\t0\t%2\tpi\tlead\tidle\t\t\tpi\t\t\t\t\t\n"
        "b\t2\t1\t%3\tclaude\tteammate\tidle\t\t\t\tgarbage\t{\tsoon\t\t\n"
        "b\t4\t0\t%4\tfzf\t\t\t\t\t\t\t\t\t\t53122 k3y\n",
    )
    panes = tmux.panes()
    reasons = (("lead", "run: ls"), ("a1", ""))
    assert panes == [
        Pane(
            *("a", 0, "%0", "claude", "lead", "working", ("lead", "a1"), 1763500000, "claude"),
            *(reasons, "fix it; now", 1763499000),
            session_id=ID,
        ),
        Pane("a", 1, "%1", "zsh"),
        Pane("b", 2, "%2", "pi", "lead", "idle", agent="pi"),
        Pane("b", 2, "%3", "claude", "teammate", "idle", index=1),
        Pane("b", 4, "%4", "fzf", sidebar="53122 k3y"),
    ]
    assert [(p.is_agent, p.state) for p in panes] == [
        (True, "needs"),
        (False, "idle"),
        (True, "idle"),
        (True, "idle"),
        (False, "idle"),
    ]
    assert stubs.tmux.calls() == [["list-panes", "-a", "-F", PANES_FORMAT]]


def test_an_unknown_role_is_not_an_agent():
    assert not Pane("a", 0, "%0", "zsh", "bogus", "working").is_agent


def test_agents_by_session_keeps_only_agents_in_pane_order():
    panes = tmux.parse_panes(
        "a\t0\t0\t%0\tzsh\t\t\t\t\t\t\t\t\t\t\n"
        "a\t1\t0\t%3\tclaude\tteammate\tdone\t\t\t\t\t\t\t\t\n"
        "b\t0\t0\t%1\tclaude\tlead\tidle\t\t\t\t\t\t\t\t\n"
        "a\t2\t0\t%2\tclaude\tlead\tworking\t\t\t\t\t\t\t\t\n"
    )
    found = tmux.agents_by_session(panes)
    assert {name: [p.id for p in agents] for name, agents in found.items()} == {
        "a": ["%3", "%2"],
        "b": ["%1"],
    }


def agent(pane: str, window: int, index: int, role: str = "lead", turn: str = "idle", *pending):
    return Pane("s", window, pane, "claude", role, turn, pending, index=index)


@pytest.mark.parametrize(
    ("agents", "first"),
    [
        ([agent("%1", 0, 0, "lead", "done"), agent("%2", 1, 0, "lead", "idle", "a1")], "%2"),
        ([agent("%1", 0, 0, "lead", "working"), agent("%2", 1, 0, "lead", "done")], "%2"),
        ([agent("%1", 0, 0, "lead", "idle"), agent("%2", 1, 0, "lead", "working")], "%2"),
        ([agent("%1", 0, 0, "lead", "done"), agent("%2", 3, 0, "teammate", "idle", "a1")], "%2"),
        ([agent("%1", 0, 0, "teammate"), agent("%2", 1, 1, "lead")], "%2"),
        ([agent("%1", 2, 0), agent("%2", 1, 1)], "%2"),
        ([agent("%1", 1, 1), agent("%2", 1, 0)], "%2"),
    ],
)
def test_the_most_urgent_agent_then_the_lead_then_the_lowest_window_and_pane(agents, first):
    for order in itertools.permutations(agents):
        assert tmux.most_urgent(order).id == first


def test_no_agents_have_no_most_urgent():
    assert tmux.most_urgent([]) is None


def test_no_server_reads_nothing(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running on /tmp/tmux-0/default\n")
    assert tmux.sessions() == []
    assert tmux.panes() == []


def test_a_slow_command_gives_none(monkeypatch):
    monkeypatch.setattr(run, "TIMEOUT", 0.2)
    assert run.output(sys.executable, "-c", "import time; time.sleep(5)") is None
    assert run.output("/nonexistent/command") is None
    assert run.output(sys.executable, "-c", "print('ok')") == "ok\n"
