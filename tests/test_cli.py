"""The command-line contract, through the installed console script."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from switchboard import __version__

SCRIPT = os.path.join(os.path.dirname(sys.executable), "switchboard")
STOP = json.dumps({"hook_event_name": "Stop", "session_id": "s"})


def run(*args: str, stdin: str | None = None, command: tuple[str, ...] = (SCRIPT,)):
    return subprocess.run(
        [*command, *args],
        input=stdin,
        stdin=subprocess.DEVNULL if stdin is None else None,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("command", [(SCRIPT,), (sys.executable, "-m", "switchboard")])
@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version(command, flag):
    result = run(flag, command=command)
    assert result.returncode == 0
    assert result.stdout == f"switchboard {__version__}\n"


def test_help_lists_the_commands():
    result = run("--help")
    assert result.returncode == 0
    assert result.stdout.startswith("usage: switchboard")
    for command in ("hook", "seen", "refresh"):
        assert command in result.stdout


@pytest.mark.parametrize("payload", [None, "", "{}", STOP, "not json {"])
@pytest.mark.parametrize("inside_tmux", [False, True])
def test_hook_is_silent(stubs, monkeypatch, payload, inside_tmux):
    if inside_tmux:
        monkeypatch.setenv("TMUX", "/nonexistent/stub,1,0")
        monkeypatch.setenv("TMUX_PANE", "%1")
    result = run("hook", "Stop", stdin=payload)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    if not inside_tmux:
        assert stubs.tmux.calls() == []


@pytest.mark.parametrize("args", [[], ["NoSuchEvent"], ["Stop", "--bogus", "extra"], ["--help"]])
def test_hook_is_silent_on_bad_arguments(stubs, args):
    result = run("hook", *args, stdin=STOP)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls() == []


@pytest.mark.parametrize("command", ["seen", "refresh"])
def test_outside_tmux_commands_exit_quietly(command):
    result = run(command)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_the_picker_is_not_built_yet(stubs):
    result = run()
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "switchboard: the picker isn't built yet\n"
    assert stubs.tmux.calls() == []
    assert stubs.fzf.calls() == []
