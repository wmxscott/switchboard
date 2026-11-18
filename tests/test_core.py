"""The core verbs, the adapter contract, the registry, `switchboard state`, the agent's label
and the pane guard, against the stub tmux and a stub `ps`.

A pane's state is written `role:turn:pending` here, as in `lead:working:a1,lead`.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from switchboard import agents, cli, core, hook, panestate
from switchboard.agents import claude

PANE = "%7"
FORMAT = "#{session_name}\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}"
CLIENTS = [";", "list-clients", "-F", "#{client_name}\t#{client_session}"]
READ = ["display-message", "-p", "-t", PANE, FORMAT, *CLIENTS]
GUARDED_READ = ["display-message", "-p", "-t", PANE, f"{FORMAT}\t#{{pane_pid}}", *CLIENTS]


def apply(before: str, *verbs: core.Verb, viewed: bool = False) -> str:
    role, turn, pending = before.split(":")
    return ":".join(core.apply((role, turn, pending), list(verbs), viewed))


@pytest.mark.parametrize(
    ("before", "verbs", "after"),
    [
        ("teammate:done:a1,lead", [core.START], "lead:idle:"),
        ("lead:idle:", [core.WORKING], "lead:working:"),
        ("lead:working:", [core.DONE], "lead:done:"),
        ("teammate:working:", [core.DONE], "teammate:idle:"),
        ("lead:done:", [core.IDLE], "lead:idle:"),
        ("lead:working:", [core.TEAMMATE], "teammate:working:"),
        ("lead:working:", [core.TEAMMATE, core.DONE], "teammate:idle:"),
        ("lead:working:lead", [core.needs("a1")], "lead:working:a1,lead"),
        ("lead:working:a1,lead", [core.resolve("a1")], "lead:working:lead"),
        ("lead:working:a1,lead", [core.RESOLVE_ALL], "lead:working:"),
        ("lead:working:", [core.resolve("a1")], "lead:working:"),
        ("::", [], "lead:idle:"),
        ("bogus:bogus:", [], "lead:idle:"),
        ("lead:working:", [core.START, core.TEAMMATE, core.WORKING], "teammate:working:"),
    ],
)
def test_each_verb(before, verbs, after):
    assert apply(before, *verbs) == after


def test_done_in_a_session_a_client_is_viewing_goes_idle():
    assert apply("lead:working:", core.DONE, viewed=True) == "lead:idle:"


@pytest.mark.parametrize(("key", "clean"), [("a,b", "a_b"), ("a;b", "a_b"), ("*", "_")])
def test_keys_are_cleaned_so_none_is_all(key, clean):
    assert core.needs(key) == core.Verb("needs", clean)
    assert core.resolve(key) == core.Verb("resolve", clean)
    assert core.resolve(key) != core.RESOLVE_ALL


def stored(stubs, state: str = "lead:working:", pid: int | None = None) -> None:
    """The pane's state, and its process id for a guarded read."""
    first = "work\t" + state.replace(":", "\t") + ("" if pid is None else f"\t{pid}")
    lines = [first, "/dev/ttys001\telsewhere"]
    stubs.tmux.answer("display-message", stdout="\n".join(lines) + "\n")


def written(stubs) -> dict[str, str | None] | None:
    """The options the write set, None for each it unset; None when nothing was written."""
    writes = [call for call in stubs.tmux.calls() if call[0] == "set-option"]
    if not writes:
        return None
    options: dict[str, str | None] = {}
    command: list[str] = []
    for arg in [*writes[0], ";"]:
        if arg != ";":
            command.append(arg)
            continue
        unset = "-u" in command
        options[command[-1] if unset else command[-2]] = None if unset else command[-1]
        command = []
    return options


def after(stubs) -> str | None:
    options = written(stubs)
    if options is None:
        return None
    return ":".join(options[o] or "" for o in (panestate.ROLE, panestate.TURN, panestate.PENDING))


def adapter(verbs=None, early=None) -> SimpleNamespace:
    """An adapter that handles `go`, logging each `verbs` call's state."""
    seen: list[core.State] = []

    def mapping(event, payload, state):
        seen.append(state)
        return list(verbs or [])

    found = SimpleNamespace(HANDLED=frozenset({"go"}), verbs=mapping, seen=seen)
    if early is not None:
        found.early = lambda event, payload: early
    return found


def test_an_unhandled_event_never_calls_tmux(stubs):
    found = adapter([core.WORKING])
    core.handle(found, "other", {}, PANE)
    assert stubs.tmux.calls() == []
    assert found.seen == []


def test_verbs_get_the_stored_state_and_apply_after_one_read(stubs):
    stored(stubs, "lead:idle:a1,lead")
    found = adapter([core.WORKING])
    core.handle(found, "go", {}, PANE)
    assert found.seen == [core.State(PANE, "lead", "idle", ("a1", "lead"))]
    assert after(stubs) == "lead:working:a1,lead"
    assert [call[0] for call in stubs.tmux.calls()] == [
        "display-message",
        "set-option",
        "list-sessions",
    ]


def test_no_verbs_still_registers_an_unknown_pane(stubs):
    stored(stubs, "::")
    core.handle(adapter([]), "go", {}, PANE)
    assert after(stubs) == "lead:idle:"


def test_no_change_writes_nothing(stubs):
    stored(stubs, "lead:working:")
    core.handle(adapter([core.WORKING]), "go", {}, PANE)
    assert [call[0] for call in stubs.tmux.calls()] == ["display-message"]


def test_early_nothing_never_calls_tmux(stubs):
    found = adapter([core.WORKING], early=[])
    core.handle(found, "go", {}, PANE)
    assert stubs.tmux.calls() == []
    assert found.seen == []


def test_early_verbs_apply_without_asking_verbs(stubs):
    stored(stubs, "lead:idle:")
    found = adapter([core.DONE], early=[core.WORKING])
    core.handle(found, "go", {}, PANE)
    assert after(stubs) == "lead:working:"
    assert found.seen == []


@pytest.mark.parametrize("early", [[core.END], None])
def test_end_unsets_every_option_then_refreshes(stubs, early):
    stored(stubs)
    core.handle(adapter([core.END], early=early), "go", {}, PANE)
    assert written(stubs) == dict.fromkeys(panestate.OPTIONS)
    reads = ["display-message"] if early is None else []
    assert [call[0] for call in stubs.tmux.calls()] == [*reads, "set-option", "list-sessions"]


def test_the_registry_finds_claude():
    assert agents.get("claude") is claude


@pytest.mark.parametrize("name", ["nope", "", "_private", "../claude", "claude.x", "os"])
def test_the_registry_knows_no_other_agent(name):
    assert agents.get(name) is None


@pytest.mark.parametrize(
    "args", [["--agent", "nope", "Stop"], ["Stop", "--agent", "_x"], ["Stop", "--agent"]]
)
def test_an_unknown_agent_is_a_silent_no_op(stubs, args):
    stored(stubs)
    hook.handle(args, PANE, json.dumps({"hook_event_name": "Stop"}).encode())
    assert stubs.tmux.calls() == []


def test_a_write_labels_the_pane_claude_by_default(stubs):
    stored(stubs, "lead:idle:")
    core.handle(adapter([core.WORKING]), "go", {}, PANE)
    assert written(stubs)[panestate.AGENT] == "claude"


def state(*args: str) -> int:
    return cli.main(["state", *args])


@pytest.fixture
def pane(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", PANE)


@pytest.mark.parametrize(
    ("args", "before", "expected"),
    [
        (["start"], "teammate:done:a1,lead", "lead:idle:"),
        (["working"], "lead:idle:", "lead:working:"),
        (["done"], "lead:working:", "lead:done:"),
        (["idle"], "lead:done:", "lead:idle:"),
        (["needs", "a1"], "lead:working:lead", "lead:working:a1,lead"),
        (["resolve", "a1"], "lead:working:a1,lead", "lead:working:lead"),
        (["resolve", "all"], "lead:working:a1,lead", "lead:working:"),
        (["resolve", "x,y"], "lead:working:x_y", "lead:working:"),
    ],
)
def test_each_state_verb(stubs, pane, capsys, args, before, expected):
    stored(stubs, before)
    assert state(*args) == 0
    assert after(stubs) == expected
    assert written(stubs)[panestate.AGENT] == "claude"
    assert stubs.tmux.calls()[0] == READ
    assert capsys.readouterr() == ("", "")


def test_state_end_unsets_every_option_without_reading(stubs, pane):
    assert state("end") == 0
    assert written(stubs) == dict.fromkeys(panestate.OPTIONS)
    assert [call[0] for call in stubs.tmux.calls()] == ["set-option", "list-sessions"]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["bogus"],
        ["teammate"],
        ["needs"],
        ["needs", ""],
        ["resolve"],
        ["working", "a1"],
        ["needs", "a1", "a2"],
        ["working", "--agent"],
        ["working", "--agent", ""],
        ["working", "--agent", "a b"],
        ["working", "--bogus"],
        ["--help"],
    ],
)
def test_malformed_state_arguments_exit_2_with_one_line(stubs, pane, capsys, args):
    assert state(*args) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"usage: switchboard state {cli.STATE_USAGE}\n"
    assert stubs.tmux.calls() == []


@pytest.fixture
def ps(tmp_path):
    """A stub `ps` first on PATH. `ancestors(...)` lists them as this process's parents, nearest
    first, with an unrelated process 999 beside them."""
    out, log, path = tmp_path / "ps-out", tmp_path / "ps-log", tmp_path / "bin" / "ps"

    def ancestors(*pids: int, code: int = 0) -> None:
        chain = [os.getpid(), *pids, 1, 0]
        rows = [*itertools.pairwise(chain), (999, 1)]
        out.write_text("".join(f"{pid:>6} {parent:>6}\n" for pid, parent in rows))
        path.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\ncat "{out}"\nexit {code}\n')
        path.chmod(0o755)

    def calls() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    ancestors(500, 400)
    return SimpleNamespace(ancestors=ancestors, calls=calls)


def test_another_agents_write_from_inside_its_pane_is_labelled(stubs, pane, ps):
    stored(stubs, "lead:idle:", pid=400)
    assert state("working", "--agent", "pi") == 0
    assert after(stubs) == "lead:working:"
    assert written(stubs)[panestate.AGENT] == "pi"
    assert stubs.tmux.calls()[0] == GUARDED_READ
    assert ps.calls() == ["-axo pid=,ppid="]


@pytest.mark.parametrize("args", [["working"], ["end"]])
def test_another_agents_event_from_outside_its_pane_is_dropped(stubs, pane, ps, args):
    stored(stubs, "lead:idle:", pid=999)
    assert state(*args, "--agent", "codex") == 0
    assert stubs.tmux.calls() == [GUARDED_READ]
    assert ps.calls() == ["-axo pid=,ppid="]


def test_another_agents_end_from_inside_unsets_every_option(stubs, pane, ps):
    stored(stubs, "lead:idle:", pid=500)
    assert state("end", "--agent", "pi") == 0
    assert written(stubs) == dict.fromkeys(panestate.OPTIONS)
    assert [call[0] for call in stubs.tmux.calls()] == [
        "display-message",
        "set-option",
        "list-sessions",
    ]


def test_a_failing_ps_drops_the_event(stubs, pane, ps):
    ps.ancestors(500, 400, code=1)
    stored(stubs, "lead:idle:", pid=400)
    assert state("working", "--agent", "pi") == 0
    assert stubs.tmux.calls() == [GUARDED_READ]


def test_the_guard_runs_only_on_a_write(stubs, pane, ps):
    stored(stubs, "lead:working:", pid=999)
    assert state("working", "--agent", "pi") == 0
    assert stubs.tmux.calls() == [GUARDED_READ]
    assert ps.calls() == []


def test_claude_never_runs_ps(stubs, pane, ps):
    stored(stubs, "lead:idle:")
    assert state("working") == 0
    hook.handle(["Stop"], PANE, json.dumps({"hook_event_name": "Stop"}).encode())
    assert after(stubs) == "lead:working:"
    assert stubs.tmux.calls()[0] == READ
    assert ps.calls() == []


@pytest.fixture
def fake(monkeypatch):
    """An adapter, `fake`, whose `go` event sets the turn working."""
    module = ModuleType("switchboard.agents.fake")
    module.HANDLED = frozenset({"go"})
    module.verbs = lambda event, payload, state: [core.WORKING]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


@pytest.mark.parametrize(("pid", "expected"), [(400, "lead:working:"), (999, None)])
def test_hook_agent_selects_the_adapter_and_guards_the_pane(stubs, ps, fake, pid, expected):
    stored(stubs, "lead:idle:", pid=pid)
    hook.handle(["--agent", "fake", "go"], PANE, b"{}")
    assert stubs.tmux.calls()[0] == GUARDED_READ
    assert after(stubs) == expected
    if expected:
        assert written(stubs)[panestate.AGENT] == "fake"


def test_a_cycle_in_the_process_table_ends_the_search(ps, tmp_path):
    (tmp_path / "ps-out").write_text(f"{os.getpid()} 500\n500 501\n501 500\n")
    assert not core.ancestor("999")
    assert core.ancestor("501")
