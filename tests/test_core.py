"""The core verbs, the adapter contract and the registry, against the stub tmux.

A pane's state is written `role:turn:pending` here, as in `lead:working:a1,lead`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from switchboard import agents, core, hook, panestate
from switchboard.agents import claude

PANE = "%7"


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


def stored(stubs, state: str = "lead:working:") -> None:
    lines = ["work\t" + state.replace(":", "\t"), "/dev/ttys001\telsewhere"]
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


def test_an_unknown_agent_is_a_silent_no_op(stubs, monkeypatch):
    stored(stubs)
    monkeypatch.setattr(hook, "AGENT", "nope")
    hook.handle(["Stop"], PANE, json.dumps({"hook_event_name": "Stop"}).encode())
    assert stubs.tmux.calls() == []
