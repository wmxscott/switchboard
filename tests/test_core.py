"""The core verbs, the adapter contract, the registry, `switchboard state`, the agent's label
and the pane guard, against the stub tmux and a stub `ps`.

A pane's state is written `role:turn:pending` here, as in `lead:working:a1,lead`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from switchboard import agents, cli, core, hook, panestate
from switchboard.agents import claude

PANE = "%7"
FORMAT = (
    "#{session_name}\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}"
    "\t#{@switchboard-reasons}\t#{@switchboard-task}\t#{@switchboard-session-id}"
)
CLIENTS = [
    ";",
    "list-clients",
    "-F",
    "#{client_name}\t#{?#{P:#{@switchboard-sidebar}},1,}\t#{client_session}",
]
READ = ["display-message", "-p", "-t", PANE, FORMAT, *CLIENTS]
GUARDED_READ = ["display-message", "-p", "-t", PANE, f"{FORMAT}\t#{{pane_pid}}", *CLIENTS]


def apply(before: str, *verbs: core.Verb, viewed: bool = False) -> str:
    role, turn, pending = before.split(":")
    return ":".join(core.apply((role, turn, pending, "", "", ""), list(verbs), viewed)[:3])


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


Reasons = dict[str, str]


def holding(reasons: Reasons, task: str = "", turn: str = "working") -> core.Stored:
    """A lead's stored state, pending `reasons`."""
    pending = panestate.encode_pending(reasons)
    found = panestate.encode_reasons(reasons)
    return ("lead", turn, pending, found, panestate.encode_task(task), "s1")


def why(reasons: Reasons, task: str, *verbs: core.Verb) -> tuple[str, Reasons, str]:
    """The pending keys, reasons and task that `verbs` make of a working lead's."""
    _, _, pending, found, task, _ = core.apply(holding(reasons, task), list(verbs), False)
    return pending, panestate.decode_reasons(found), panestate.decode_task(task)


XY = {"x": "run: ls", "y": "asks: ok?"}


@pytest.mark.parametrize(
    ("verbs", "after"),
    [
        ([core.needs("z", "edit: a.py")], ("x,y,z", {**XY, "z": "edit: a.py"}, "fix it")),
        ([core.needs("z")], ("x,y,z", {**XY, "z": ""}, "fix it")),
        ([core.needs("x", "run: ls")], ("x,y", XY, "fix it")),
        ([core.needs("x", "run: pwd")], ("x,y", {"y": "asks: ok?", "x": "run: pwd"}, "fix it")),
        ([core.needs("x")], ("x,y", {"y": "asks: ok?", "x": ""}, "fix it")),
        ([core.resolve("x")], ("y", {"y": "asks: ok?"}, "fix it")),
        ([core.resolve("z")], ("x,y", XY, "fix it")),
        ([core.RESOLVE_ALL], ("", {}, "fix it")),
        ([core.working("add a test")], ("x,y", XY, "add a test")),
        ([core.working()], ("x,y", XY, "fix it")),
        ([core.WORKING], ("x,y", XY, "fix it")),
        ([core.DONE], ("x,y", XY, "fix it")),
        ([core.IDLE], ("x,y", XY, "fix it")),
        ([core.TEAMMATE], ("x,y", XY, "fix it")),
        ([core.START], ("", {}, "")),
        ([core.START, core.needs("x", "run: ls")], ("x", {"x": "run: ls"}, "")),
    ],
)
def test_each_verb_on_reasons_and_the_task(verbs, after):
    pending, reasons, task = why(XY, "fix it", *verbs)
    assert (pending, list(reasons.items()), task) == (after[0], list(after[1].items()), after[2])


def test_a_pending_key_with_no_reason_stored_has_the_plain_one():
    older = ("lead", "working", "x", "", "", "")
    assert core.apply(older, [core.needs("x")], False) == older
    assert core.apply(older, [core.needs("x", "run: ls")], False)[3] == '{"x":"run: ls"}'


def test_reasons_never_outlive_their_keys():
    stale = ("lead", "working", "x", panestate.encode_reasons({"x": "a", "gone": "b"}), "", "")
    assert core.apply(stale, [], False)[3] == panestate.encode_reasons({"x": "a"})


@pytest.mark.parametrize(
    ("verbs", "after"),
    [
        ([core.session("s2")], "s2"),
        ([core.session("s1")], "s1"),
        ([core.session("")], "s1"),
        ([core.session(None)], "s1"),
        ([core.session("a;b")], "s1"),
        ([core.START], ""),
        ([core.START, core.session("s2")], "s2"),
        ([core.session("s2"), core.START], ""),
        ([core.WORKING, core.DONE, core.needs("x"), core.RESOLVE_ALL, core.TEAMMATE], "s1"),
    ],
)
def test_each_verb_on_the_session_id(verbs, after):
    assert core.apply(holding({}), verbs, False)[5] == after


def test_a_session_id_is_cleaned_as_stored():
    assert core.session("3f1c9e2a-7b4d") == core.Verb("session", "", "3f1c9e2a-7b4d")
    assert core.session("a\tb") == core.session(None) == core.Verb("session", "", "")


def test_verbs_carry_their_text_as_stored():
    assert core.needs("a1", " run:\n  ls\x1b ") == core.Verb("needs", "a1", "run: ls")
    assert core.working("fix\tthe login\n") == core.Verb("working", "", "fix the login")
    assert core.working() == core.WORKING


def raises(reasons: Reasons, *verbs: core.Verb, turn: str = "working", viewed=False) -> bool:
    before = holding(reasons, turn=turn)
    return core.raised(before, core.apply(before, list(verbs), viewed))


@pytest.mark.parametrize(
    ("reasons", "verbs", "turn", "card"),
    [
        ({}, [core.needs("x", "run: ls")], "working", True),
        ({"x": "run: ls"}, [core.needs("y")], "working", True),
        (XY, [core.needs("y", "asks: ok?")], "working", False),
        (XY, [core.needs("x", "run: ls")], "working", False),
        ({"x": "run: ls"}, [core.needs("x", "run: pwd")], "working", True),
        ({}, [core.DONE], "working", True),
        ({"x": ""}, [core.resolve("x"), core.DONE], "working", True),
        (XY, [core.resolve("y")], "working", False),
        (XY, [core.RESOLVE_ALL], "working", False),
        (XY, [core.WORKING], "idle", False),
        ({}, [core.working("fix it")], "idle", False),
        ({}, [core.IDLE], "done", False),
        ({}, [core.DONE], "done", False),
        ({"x": ""}, [core.START, core.WORKING], "done", False),
    ],
)
def test_the_card_time_moves_on_a_new_prompt_or_a_turn_done(reasons, verbs, turn, card):
    assert raises(reasons, *verbs, turn=turn) == card


def test_a_turn_done_where_a_client_is_looking_moves_no_card_time():
    assert not raises({}, core.DONE, viewed=True)


def stored(
    stubs,
    state: str = "lead:working:",
    pid: int | None = None,
    reasons: str = "",
    task: str = "",
    session_id: str = "",
) -> None:
    """The pane's state, and its process id for a guarded read."""
    first = "\t".join(["work", *state.split(":"), reasons, task, session_id])
    first += "" if pid is None else f"\t{pid}"
    lines = [first, "/dev/ttys001\t\telsewhere"]
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


def test_the_read_gives_each_client_its_session_and_whether_its_window_has_a_sidebar(stubs):
    lines = [
        "work\tlead\tidle\t\t\t\ts1",
        "/dev/ttys001\t1\tmy\tsession",
        "/dev/ttys002\t\twork",
        "junk",
    ]
    stubs.tmux.answer("display-message", stdout="\n".join(lines) + "\n")
    view = core.read(PANE)
    assert view.clients == [
        ("/dev/ttys001", "my\tsession", True),
        ("/dev/ttys002", "work", False),
    ]
    assert view.stored == ("lead", "idle", "", "", "", "s1")
    assert stubs.tmux.calls() == [READ]


def test_no_verbs_still_registers_an_unknown_pane(stubs):
    stored(stubs, "::")
    core.handle(adapter([]), "go", {}, PANE)
    assert after(stubs) == "lead:idle:"


def recent(value: str | None) -> bool:
    return value is not None and abs(int(value) - time.time()) < 60


def test_a_reason_is_written_once_with_the_card_time(stubs):
    stored(stubs, "lead:working:", task=panestate.encode_task("fix it"))
    core.perform(PANE, [core.needs("x", "run: ls")])
    options = written(stubs)
    assert options[panestate.PENDING] == "x"
    assert options[panestate.REASONS] == '{"x":"run: ls"}'
    assert options[panestate.TASK] == '"fix it"'
    assert recent(options[panestate.CARD_AT])
    assert recent(options[panestate.AT])
    assert [call[0] for call in stubs.tmux.calls()].count("set-option") == 1


def test_resolving_the_last_reason_unsets_it_and_keeps_the_card_time(stubs):
    stored(stubs, "lead:working:x", reasons='{"x":"run: ls"}')
    core.perform(PANE, [core.resolve("x")])
    options = written(stubs)
    assert options[panestate.REASONS] is None
    assert options[panestate.TASK] is None
    assert panestate.CARD_AT not in options


def test_the_same_prompt_again_writes_nothing(stubs):
    stored(stubs, "lead:working:x,y", reasons='{"x":"run: ls","y":""}', task='"fix it"')
    core.perform(PANE, [core.needs("x", "run: ls"), core.working()])
    assert [call[0] for call in stubs.tmux.calls()] == ["display-message"]


def test_no_change_writes_nothing(stubs):
    stored(stubs, "lead:working:")
    core.handle(adapter([core.WORKING]), "go", {}, PANE)
    assert [call[0] for call in stubs.tmux.calls()] == ["display-message"]


def test_a_new_session_id_alone_is_written_with_the_state_in_the_one_write(stubs):
    stored(stubs, "lead:working:x", reasons='{"x":"run: ls"}', session_id="s1")
    core.perform(PANE, [core.session("s2")])
    options = written(stubs)
    assert options[panestate.SESSION_ID] == "s2"
    assert (after(stubs), options[panestate.REASONS]) == ("lead:working:x", '{"x":"run: ls"}')
    assert panestate.CARD_AT not in options
    calls = [call[0] for call in stubs.tmux.calls()]
    assert calls == ["display-message", "set-option", "list-sessions"]


def test_the_same_session_id_writes_nothing(stubs):
    stored(stubs, "lead:working:", session_id="s1")
    core.perform(PANE, [core.session("s1"), core.WORKING])
    assert [call[0] for call in stubs.tmux.calls()] == ["display-message"]


def test_a_write_with_no_session_id_unsets_it(stubs):
    stored(stubs, "lead:working:", session_id="s1")
    core.perform(PANE, [core.START])
    assert written(stubs)[panestate.SESSION_ID] is None


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
        (["needs", "a1", "--reason", "run: ls"], "lead:working:lead", "lead:working:a1,lead"),
        (["working", "--task", "fix it"], "lead:idle:", "lead:working:"),
    ],
)
def test_each_state_verb(stubs, pane, capsys, args, before, expected):
    stored(stubs, before)
    assert state(*args) == 0
    assert after(stubs) == expected
    assert written(stubs)[panestate.AGENT] == "claude"
    assert stubs.tmux.calls()[0] == READ
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("args", "option", "value"),
    [
        (["needs", "x", "--reason", "run:\n  ls -la"], panestate.REASONS, '{"x":"run: ls -la"}'),
        (["needs", "x", "--reason", ""], panestate.REASONS, '{"x":""}'),
        (["needs", "x", "--agent", "claude", "--reason", "a;"], panestate.REASONS, '{"x":"a;"}'),
        (["working", "--task", "fix the login"], panestate.TASK, '"fix the login"'),
        (["--agent", "claude", "working", "--task", "a\tb"], panestate.TASK, '"a b"'),
    ],
)
def test_state_stores_a_reason_or_a_task(stubs, pane, capsys, args, option, value):
    stored(stubs, "lead:idle:")
    assert state(*args) == 0
    assert written(stubs)[option] == value
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
        ["needs", "x", "--reason"],
        ["needs", "--reason", "run: ls"],
        ["needs", "x", "--reason", "a", "b"],
        ["needs", "x", "--task", "t"],
        ["working", "--task"],
        ["working", "--task", "a", "b"],
        ["working", "--reason", "t"],
        ["done", "--task", "t"],
        ["resolve", "x", "--reason", "t"],
    ],
)
def test_malformed_state_arguments_exit_2_with_one_line(stubs, pane, capsys, args):
    assert state(*args) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"usage: switchboard state {cli.STATE_USAGE}\n"
    assert stubs.tmux.calls() == []


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
