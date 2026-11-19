"""The stub `tmux` and `fzf` that every test runs against."""

from __future__ import annotations

import subprocess


def call(*args: str, stdin: str = ""):
    return subprocess.run(list(args), input=stdin, capture_output=True, text=True, timeout=30)


def test_tmux_logs_every_call_and_answers_by_subcommand(stubs):
    stubs.tmux.answer("list-sessions", stdout="a\t/x\n")
    stubs.tmux.answer("switch-client", code=1, stderr="no client\n")
    listed = call("tmux", "list-sessions", "-F", "#{session_name}")
    switched = call("tmux", "switch-client", "-t", "=a")
    unanswered = call("tmux", "set-option", "-p", "@x", "1")
    assert (listed.returncode, listed.stdout) == (0, "a\t/x\n")
    assert (switched.returncode, switched.stderr) == (1, "no client\n")
    assert (unanswered.returncode, unanswered.stdout, unanswered.stderr) == (0, "", "")
    assert stubs.tmux.calls() == [
        ["list-sessions", "-F", "#{session_name}"],
        ["switch-client", "-t", "=a"],
        ["set-option", "-p", "@x", "1"],
    ]


def test_tmux_wildcard_answers_everything_else(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running\n")
    stubs.tmux.answer("list-sessions", stdout="a\n")
    assert call("tmux", "list-sessions").stdout == "a\n"
    failed = call("tmux", "display-message", "-p", "#{client_name}")
    assert (failed.returncode, failed.stderr) == (1, "no server running\n")


def test_tmux_answers_a_whole_command_line_before_its_subcommand(stubs):
    stubs.tmux.answer("switch-client", stdout="any\n")
    stubs.tmux.answer("switch-client -t %1", code=1, stderr="can't find pane: %1\n")
    gone = call("tmux", "switch-client", "-t", "%1")
    assert (gone.returncode, gone.stderr) == (1, "can't find pane: %1\n")
    assert call("tmux", "switch-client", "-t", "=a").stdout == "any\n"


def test_fzf_replays_one_reply_per_call(stubs):
    stubs.fzf.reply("b\n")
    stubs.fzf.reply(code=130)
    first = call("fzf", "--no-sort", stdin="a\nb\n")
    second = call("fzf", stdin="c\n")
    third = call("fzf")
    assert (first.returncode, first.stdout) == (0, "b\n")
    assert (second.returncode, second.stdout) == (130, "")
    assert third.returncode == 98
    assert third.stderr == "stub fzf: no reply for call 3\n"
    assert stubs.fzf.calls() == [
        {"args": ["--no-sort"], "stdin": "a\nb\n"},
        {"args": [], "stdin": "c\n"},
        {"args": [], "stdin": ""},
    ]
