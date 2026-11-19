"""`@attention`, `switchboard refresh` and `switchboard seen`, against the stub tmux."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

import pytest

from switchboard import attention
from switchboard.panestate import DONE, IDLE, NEEDS, WORKING

SCRIPT = os.path.join(os.path.dirname(sys.executable), "switchboard")
R, G, H = "#[fg=themered]", "#[fg=themegreen]", "#[fg=themelightgrey]"
END = "#[default] "


def plain(value: str) -> str:
    return re.sub(r"#\[[^]]*\]", "", value).replace("##", "#")


def sessions(stubs, *names: str, **values: str) -> None:
    """Answers list-sessions with `names`, each holding `values[name]` as its `@attention`."""
    text = "".join(f"{name}\t\t/tmp\t0\t{values.get(name, '')}\n" for name in names)
    stubs.tmux.answer("list-sessions", stdout=text)


def panes(stubs, *rows: str) -> None:
    """Each row is `session:pane:role:turn:pending`."""
    text = "".join("{}\t0\t{}\tclaude\t{}\t{}\t{}\t0\t\t\n".format(*row.split(":")) for row in rows)
    stubs.tmux.answer("list-panes", stdout=text)


def commands(call: list[str]) -> list[list[str]]:
    found: list[list[str]] = [[]]
    for arg in call:
        if arg == ";":
            found.append([])
        else:
            found[-1].append(arg)
    return found


def written(stubs) -> dict[str, str] | None:
    """Each session's `@attention` from the one call that writes them; None without that call."""
    writes = [c for c in stubs.tmux.calls() if c[0] == "set-option" and "@attention" in c]
    assert len(writes) <= 1
    if not writes:
        return None
    values = {}
    for command in commands(writes[0]):
        assert command[:2] == ["set-option", "-t"]
        assert command[3] == "@attention"
        values[command[2].removeprefix("=").removesuffix(":")] = command[4]
    return values


def run(*args: str, **env: str):
    return subprocess.run(
        [SCRIPT, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **env},
    )


def test_names_need_you_first_then_done_each_in_order():
    states = {
        "zeta": [NEEDS],
        "Done/b": [DONE],
        "beta": [NEEDS],
        "done/a": [DONE],
        "gamma": [WORKING],
        "delta": [IDLE],
        "eps": [],
    }
    assert attention.render(states, "delta") == (
        f"{R}▲ beta  {R}▲ zeta  {G}✓ done/a  {G}✓ Done/b{END}"
    )


def test_your_own_session_is_left_out():
    states = {"mine": [NEEDS, NEEDS], "theirs": [DONE]}
    assert attention.render(states, "mine") == f"{G}✓ theirs{END}"
    assert attention.render(states, "theirs") == f"{R}▲² mine{END}"
    assert attention.render({"mine": [DONE]}, "mine") == ""


def test_nothing_to_show_is_empty():
    assert attention.render({}, "a") == ""
    assert attention.render({"a": [WORKING], "b": [IDLE, IDLE], "c": []}, "d") == ""


@pytest.mark.parametrize(
    ("agents", "value"),
    [
        ([NEEDS], f"{R}▲ w{END}"),
        ([WORKING, NEEDS, IDLE], f"{R}▲ w{END}"),
        ([DONE, IDLE], f"{G}✓ w{END}"),
        ([NEEDS] * 3, f"{R}▲³ w{END}"),
        ([NEEDS, DONE, NEEDS], f"{R}▲²{G}✓{R} w{END}"),
        ([DONE, WORKING, DONE], f"{G}✓² w{END}"),
        ([DONE, NEEDS], f"{R}▲{G}✓{R} w{END}"),
        ([NEEDS, DONE, DONE], f"{R}▲{G}✓²{R} w{END}"),
    ],
)
def test_a_mark_per_state_present_counted_past_one_agent(agents, value):
    assert attention.render({"w": agents}, "elsewhere") == value


def test_each_mark_keeps_its_colour_and_the_name_its_groups():
    value = attention.render({"w": [DONE] * 12 + [NEEDS] * 10}, "elsewhere")
    assert re.findall(r"#\[fg=(\w+)\]([^#]*)", value) == [
        ("themered", "▲¹⁰"),
        ("themegreen", "✓¹²"),
        ("themered", " w"),
    ]
    assert plain(value) == "▲¹⁰✓¹² w "


def test_a_session_with_any_agent_needing_you_sits_with_need_you():
    states = {"a": [DONE], "b": [DONE, DONE, NEEDS], "c": [NEEDS], "d": [DONE, WORKING]}
    assert attention.render(states, "x") == (f"{R}▲{G}✓²{R} b  {R}▲ c  {G}✓ a  {G}✓ d{END}")


def test_past_the_budget_names_become_counts_of_sessions():
    states = {f"repo/needs-{n}": [NEEDS, NEEDS] for n in range(3)}
    states |= {"repo/needs-3": [NEEDS, DONE]}
    states |= {f"repo/done-{n}": [DONE] * 3 for n in range(3)}
    value = attention.render(states, "elsewhere")
    assert value == f"{R}▲ 4 need you  {G}✓ 3 done  {H}prefix w{END}"
    assert plain(value) == "▲ 4 need you  ✓ 3 done  prefix w "


@pytest.mark.parametrize(
    ("states", "names"),
    [
        ({"n" * 58: [NEEDS]}, f"{R}▲ {'n' * 58}{END}"),
        ({"n" * 27: [NEEDS], "d" * 27: [DONE]}, f"{R}▲ {'n' * 27}  {G}✓ {'d' * 27}{END}"),
        ({"n" * 55: [NEEDS] * 10 + [DONE]}, f"{R}▲¹⁰{G}✓{R} {'n' * 55}{END}"),
        ({"n" * 26: [NEEDS] * 2, "d" * 26: [DONE] * 3}, f"{R}▲² {'n' * 26}  {G}✓³ {'d' * 26}{END}"),
    ],
)
def test_names_fill_the_budget_exactly_and_one_more_column_is_counts(states, names):
    assert attention.BUDGET == 60
    value = attention.render(states, "elsewhere")
    assert value == names
    assert len(plain(value).rstrip()) == attention.BUDGET
    longer = {name + "x": state for name, state in states.items()}
    counts = attention.render(longer, "elsewhere")
    assert plain(counts).startswith("▲ 1 needs you  ")
    assert plain(counts).endswith("prefix w ")


@pytest.mark.parametrize("agents", [[NEEDS, NEEDS], [NEEDS, DONE]])
def test_a_count_or_another_mark_can_tip_names_into_counts(agents):
    name = "n" * 58
    assert plain(attention.render({name: [NEEDS]}, "x")) == f"▲ {name} "
    assert plain(attention.render({name: agents}, "x")) == "▲ 1 needs you  prefix w "


@pytest.mark.parametrize(("state", "text"), [(NEEDS, "▲ 3 need you"), (DONE, "✓ 3 done")])
def test_counts_show_only_the_kinds_present(state, text):
    states = {f"{'x' * 25}-{n}": [state] for n in range(3)}
    assert plain(attention.render(states, "elsewhere")) == f"{text}  prefix w "


def test_a_hash_in_a_name_is_escaped():
    assert attention.render({"fix#[1]": [NEEDS]}, "x") == f"{R}▲ fix##[1]{END}"
    assert attention.render({"fix#[1]": [NEEDS, DONE]}, "x") == f"{R}▲{G}✓{R} fix##[1]{END}"


def test_refresh_writes_each_sessions_own_value_in_one_call(stubs):
    sessions(stubs, "build", "docs", "main", "scratch")
    panes(
        stubs,
        "build:%1:lead:working:lead",
        "build:%2:teammate:idle:a1",
        "docs:%3:lead:done:",
        "main:%4:lead:working:",
        "main:%5:teammate:idle:",
    )
    attention.refresh()
    assert written(stubs) == {
        "build": f"{G}✓ docs{END}",
        "docs": f"{R}▲² build{END}",
        "main": f"{R}▲² build  {G}✓ docs{END}",
        "scratch": f"{R}▲² build  {G}✓ docs{END}",
    }
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions", "list-panes", "set-option"]


def test_refresh_counts_agents_by_their_displayed_state(stubs):
    sessions(stubs, "work", "here")
    panes(
        stubs,
        "work:%1:lead:working:a1,a2,lead",
        "work:%2:lead:done:",
        "work:%3:lead:done:",
        "work:%4:teammate:working:",
        "work:%5:teammate:idle:b1",
        "here:%6:lead:idle:",
    )
    attention.refresh()
    assert written(stubs) == {"here": f"{R}▲²{G}✓²{R} work{END}"}


def test_refresh_writes_only_what_changed(stubs):
    sessions(stubs, "a", "b", "c", a=f"{G}✓ b{END}", b=f"{R}▲ gone{END}", c=f"{G}✓ b{END}")
    panes(stubs, "b:%1:lead:done:")
    attention.refresh()
    assert written(stubs) == {"b": ""}


@pytest.mark.parametrize(
    ("value", "rows"),
    [
        (f"{R}▲ b{END}", ["b:%1:lead:idle:lead"]),
        (f"{R}▲²{G}✓{R} b{END}", ["b:%1:lead:idle:lead", "b:%2:lead:done:a1", "b:%3:lead:done:"]),
    ],
)
def test_refresh_writes_nothing_when_nothing_changed(stubs, value, rows):
    sessions(stubs, "a", "b", a=value)
    panes(stubs, *rows)
    attention.refresh()
    assert written(stubs) is None
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions", "list-panes"]


def test_refresh_with_no_server_exits_quietly(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running on /tmp/tmux-0/default\n")
    result = run("refresh")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions"]


def seen_writes(stubs) -> dict[str, dict[str, str]]:
    """The pane options `seen` set, by pane, from its one pane write."""
    writes = [c for c in stubs.tmux.calls() if c[:2] == ["set-option", "-p"]]
    assert len(writes) <= 1
    found: dict[str, dict[str, str]] = {}
    for command in commands(writes[0]) if writes else []:
        assert command[:3] == ["set-option", "-p", "-t"]
        found.setdefault(command[3], {})[command[4]] = command[5]
    return found


def test_seen_turns_done_idle_but_leaves_needs_you(stubs):
    sessions(stubs, "work", "other")
    panes(
        stubs,
        "work:%1:lead:done:",
        "work:%2:lead:done:a1",
        "work:%3:teammate:working:lead",
        "work:%4:lead:idle:",
        "other:%5:lead:done:",
    )
    attention.seen("work")
    options = seen_writes(stubs)
    assert {pane: values["@switchboard-turn"] for pane, values in options.items()} == {
        "%1": "idle",
        "%2": "idle",
    }
    for values in options.values():
        assert set(values) == {"@switchboard-turn", "@switchboard-at"}
        assert abs(int(values["@switchboard-at"]) - time.time()) < 60
    assert written(stubs) == {"work": f"{G}✓ other{END}", "other": f"{R}▲² work{END}"}


def test_seen_with_nothing_done_only_refreshes(stubs):
    sessions(stubs, "work", "other")
    panes(stubs, "work:%1:lead:idle:", "other:%2:lead:done:")
    attention.seen("work")
    assert seen_writes(stubs) == {}
    assert written(stubs) == {"work": f"{G}✓ other{END}"}


def test_seen_takes_the_session_as_an_argument(stubs):
    sessions(stubs, "a b", "other")
    panes(stubs, "a b:%1:lead:done:", "other:%2:lead:done:")
    result = run("seen", "a b")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert list(seen_writes(stubs)) == ["%1"]


def test_seen_without_an_argument_uses_the_pane_session(stubs):
    stubs.tmux.answer("display-message", stdout="work\n")
    sessions(stubs, "work", "other")
    panes(stubs, "work:%1:lead:done:", "other:%2:lead:done:")
    result = run("seen", TMUX="/tmp/stub,1,0", TMUX_PANE="%1")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls()[0] == ["display-message", "-p", "-t", "%1", "#{session_name}"]
    assert list(seen_writes(stubs)) == ["%1"]


def test_seen_without_a_pane_uses_the_current_clients_session(stubs):
    stubs.tmux.answer("display-message", stdout="other\n")
    sessions(stubs, "work", "other")
    panes(stubs, "work:%1:lead:done:", "other:%2:lead:done:")
    result = run("seen", TMUX="/tmp/stub,1,0")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls()[0] == ["display-message", "-p", "#{session_name}"]
    assert list(seen_writes(stubs)) == ["%2"]


def test_seen_outside_tmux_without_an_argument_does_nothing(stubs):
    result = run("seen")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert stubs.tmux.calls() == []


def test_seen_with_no_server_exits_quietly(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running on /tmp/tmux-0/default\n")
    result = run("seen", "work")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions"]
