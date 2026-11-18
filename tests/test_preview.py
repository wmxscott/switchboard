"""The picker's preview, against the stub tmux."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from switchboard import preview

FORMAT = (
    "#{session_path}\t#{window_index}\t#{window_active}\t#{pane_id}\t#{pane_active}"
    "\t#{pane_current_command}\t#{@switchboard-role}\t#{@switchboard-turn}"
    "\t#{@switchboard-pending}\t#{@switchboard-at}\t#{@switchboard-agent}\t#{window_name}"
)


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def listing(path: str | Path, *panes: tuple) -> str:
    """Each pane is a window index, window active, pane id, pane active, command, role, turn,
    pending keys and window name, then maybe the agent's label."""
    return "".join(
        f"{path}\t{window}\t{window_on}\t{pane}\t{pane_on}\t{command}\t{role}\t{turn}\t{pending}"
        f"\t0\t{''.join(agent)}\t{name}\n"
        for window, window_on, pane, pane_on, command, role, turn, pending, name, *agent in panes
    )


def test_a_session_with_agents_shows_the_most_urgent_ones_last_lines(stubs):
    stubs.tmux.answer(
        "list-panes",
        stdout=listing(
            Path.home() / "src/widget",
            (0, 1, "%1", 1, "zsh", "", "", "", "shell"),
            (1, 0, "%2", 1, "claude", "lead", "done", "", "claude"),
            (2, 0, "%3", 0, "claude", "teammate", "working", "", "team\tnotes"),
            (2, 0, "%4", 1, "claude", "lead", "working", "a1", "team\tnotes"),
        ),
    )
    stubs.tmux.answer("capture-pane", stdout="older\n  Allow make test?   \n  1. Yes\n\n   \n\n")
    shown = preview.show("w/main", 20)
    assert plain(shown).splitlines() == [
        "w/main",
        "~/src/widget",
        "",
        "windows",
        "▸ 0 shell",
        "  1 claude ✓",
        "  2 team\tnotes ▲",
        "",
        "claude · win 2 · needs you",
        "older",
        "  Allow make test?",
        "  1. Yes",
    ]
    assert shown.startswith("\x1b[1mw/main\x1b[0m\n\x1b[90m~/src/widget\x1b[0m\n")
    assert "\x1b[36m▸\x1b[0m 0 shell\n" in shown
    assert "  2 team\tnotes \x1b[33m▲\x1b[0m\n" in shown
    assert stubs.tmux.calls() == [
        ["list-panes", "-s", "-t", "=w/main", "-F", FORMAT],
        ["capture-pane", "-p", "-J", "-t", "%4", "-S", "-11"],
    ]


def test_an_agents_pane_is_named_by_its_label(stubs):
    stubs.tmux.answer(
        "list-panes",
        stdout=listing("/srv", (0, 1, "%1", 1, "node", "lead", "done", "", "pi", "pi")),
    )
    stubs.tmux.answer("capture-pane", stdout="ok\n")
    assert plain(preview.show("s", 20)).splitlines()[-2:] == ["pi · win 0 · done", "ok"]


def test_a_session_without_agents_shows_its_active_pane(stubs):
    stubs.tmux.answer(
        "list-panes",
        stdout=listing(
            "/srv/scratch",
            (1, 0, "%1", 1, "zsh", "", "", "", "shell"),
            (2, 1, "%2", 0, "zsh", "", "", "", "build"),
            (2, 1, "%3", 1, "make", "", "", "", "build"),
        ),
    )
    stubs.tmux.answer("capture-pane", stdout="".join(f"line {n}\n" for n in range(30)) + "\n" * 9)
    assert plain(preview.show("scratch", 12)).splitlines() == [
        "scratch",
        "/srv/scratch",
        "",
        "windows",
        "  1 shell",
        "▸ 2 build",
        "",
        "make · win 2",
        "line 26",
        "line 27",
        "line 28",
        "line 29",
    ]
    assert stubs.tmux.calls()[1] == ["capture-pane", "-p", "-J", "-t", "%3", "-S", "-4"]


def test_a_repo_header_has_no_preview(stubs):
    assert preview.show("") == ""
    assert stubs.tmux.calls() == []


def test_no_room_left_skips_the_capture(stubs):
    stubs.tmux.answer(
        "list-panes", stdout=listing("/srv", (0, 1, "%1", 1, "claude", "lead", "idle", "", "c"))
    )
    assert plain(preview.show("s", 6)).splitlines() == ["s", "/srv", "", "windows", "▸ 0 c ○"]
    assert [call[0] for call in stubs.tmux.calls()] == ["list-panes"]


def test_tmux_failing_shows_what_there_is(stubs):
    stubs.tmux.answer(
        "list-panes", stdout=listing("/srv", (0, 1, "%1", 1, "zsh", "", "", "", "shell"))
    )
    stubs.tmux.answer("capture-pane", code=1, stderr="can't find pane: %1\n")
    assert plain(preview.show("s", 20)).splitlines() == ["s", "/srv", "", "windows", "▸ 0 shell"]
    stubs.tmux.answer("list-panes", code=1, stderr="can't find session: s\n")
    assert preview.show("s", 20) == "\x1b[1ms\x1b[0m\n"
    stubs.tmux.answer("list-panes", stdout="garbage\n0\t1\n")
    assert preview.show("s", 20) == "\x1b[1ms\x1b[0m\n"


def test_the_command_is_quiet_and_sized_by_fzf(stubs):
    stubs.tmux.answer("list-panes", stdout=listing("/srv", (0, 1, "%1", 1, "zsh", "", "", "", "z")))
    env = {**os.environ, "FZF_PREVIEW_LINES": "30"}
    command = [sys.executable, "-m", "switchboard", "__preview", "w/main"]
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
    assert (result.returncode, result.stderr) == (0, "")
    assert plain(result.stdout).splitlines()[:5] == ["w/main", "/srv", "", "windows", "▸ 0 z"]
    assert stubs.tmux.calls()[1][-2:] == ["-S", "-23"]
    stubs.tmux.answer("list-panes", code=1, stderr="no server running\n")
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
    assert (result.returncode, plain(result.stdout), result.stderr) == (0, "w/main\n", "")
