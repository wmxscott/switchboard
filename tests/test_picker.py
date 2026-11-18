"""The picker, against the stub tmux and fzf."""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from switchboard import cli, model, picker
from switchboard.git import Status, Worktree
from switchboard.model import Model, Repo, Row
from switchboard.projects import Label
from switchboard.tmux import Pane, Session

CLIENT = "/dev/ttys001"
KEYS = "j:down,k:up,q:abort"
DOT, FILL, OPEN, SHUT, HERE = "\uf4c3", "\uf444", "\uf0d7", "\uf0da", "\uf192"
TEXT, SUBTEXT, OVERLAY = "38;2;202;211;245", "38;2;165;173;203", "38;2;128;135;162"
RED, GREEN, PEACH = "38;2;237;135;150", "38;2;166;218;149", "38;2;245;169;127"
HINTS = "j/k move · / search · tab fold · ↵ switch · q/esc close"
SEARCH_HINTS = "↑/↓ move · tab fold · ↵ switch · esc back"


@pytest.fixture(autouse=True)
def dark(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_THEME", "dark")


def esc(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def header(hints: str) -> str:
    return f" \n{esc('2;38;2;110;115;141', hints)}\n "


def worktree(name: str, branch: str, repo: str, *agents: tuple) -> Row:
    panes = tuple(Pane(name, window, f"%{window}", "claude", *state) for window, *state in agents)
    return Row(Session(name, "", f"/src/{name}"), Worktree(f"/src/{name}", branch, repo), panes)


def fixture() -> Model:
    gadget = Repo(
        "/g/.git", "gadget", "main", (worktree("gadget", "main", "/g", (3, "lead", "done")),)
    )
    widget = Repo(
        "/w/.bare",
        "widget",
        "main",
        (
            worktree(
                "w/main", "main", "/w", (1, "lead", "working", ("lead",)), (2, "teammate", "idle")
            ),
            worktree("w/feat/x", "feat/x", "/w", (1, "lead", "working")),
            worktree("w/zed", "zed", "/w"),
        ),
        Label("W", "tools/widget"),
    )
    other = (
        Row(
            Session("scratch", "", "/tmp"),
            None,
            (Pane("scratch", 4, "%9", "claude", "lead", "idle"),),
        ),
        Row(Session("home", "", "/home"), None),
    )
    return Model((gadget, widget), other)


RENDERED = [
    ("", "0", f"{OPEN} gadget  1 done"),
    ("gadget", "0", f"│   main     {FILL}"),
    ("gadget", "0", f"│   └ {FILL} claude · win 3 · done"),
    ("", "1", f"{OPEN} W tools/widget  1 needs you · 1 working"),
    ("w/main", "1", f"│ {HERE} main     {FILL}"),
    ("w/main", "1", f"│   ├ {FILL} claude · win 1 · needs you"),
    ("w/main", "1", f"│   └ {DOT} teammate · win 2 · idle"),
    ("w/feat/x", "1", f"│   feat/x   {FILL}"),
    ("w/feat/x", "1", f"│   └ {FILL} claude · win 1 · working"),
    ("w/zed", "1", "│   zed"),
    ("", "2", f"{OPEN} other"),
    ("scratch", "2", f"│   scratch  {DOT}"),
    ("scratch", "2", f"│   └ {DOT} claude · win 4 · idle"),
    ("home", "2", "│   home"),
]


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def fields(lines) -> list[tuple[str, ...]]:
    return [tuple(plain(line).split("\t")) for line in lines]


def line_of(session: str, n: int = 0) -> str:
    """What fzf prints for `session`'s worktree line, or its `n`th agent's."""
    found = [
        line
        for line in picker.lines(picker.render(fixture(), "w/main"))
        if line.startswith(f"{session}\t")
    ]
    return plain(found[n]) + "\n"


def bindings(args: list[str]) -> dict[str, str]:
    found = {}
    for flag, value in itertools.pairwise(args):
        if flag == "--bind":
            key, _, action = value.partition(":")
            found[key] = action
    return found


def sh(command: str) -> str:
    result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=30)
    assert result.stderr == ""
    return result.stdout


def switches(stubs) -> list[list[str]]:
    return [call for call in stubs.tmux.calls() if call[0] == "switch-client"]


@pytest.fixture
def picking(stubs, monkeypatch, tmp_path):
    """Inside tmux on `w/main`, with fzf 0.59 and the fixture model."""
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    stubs.tmux.answer("display-message", stdout=f"{CLIENT}\tw/main\n")
    stubs.fzf.reply("0.59.0\n")
    return stubs


def picked(stubs) -> dict:
    version, call = stubs.fzf.calls()
    assert version["args"] == ["--version"]
    return call


def test_rows_by_repo_with_agents_and_other():
    groups = picker.render(fixture(), "w/main")
    assert fields(picker.lines(groups)) == RENDERED
    assert picker.cursor(groups, "w/main") == 5
    assert picker.cursor(groups, "gone") is None


@pytest.mark.parametrize(
    ("role", "agent", "who"),
    [("lead", "pi", "pi"), ("lead", "", "claude"), ("teammate", "codex", "teammate")],
)
def test_an_agent_row_names_its_agent(role, agent, who):
    pane = Pane("s", 2, "%2", "node", role, "working", agent=agent)
    assert picker.describe(pane) == f"{who} · win 2 · working"


def test_row_colours():
    lines = [line.split("\t")[2] for line in picker.lines(picker.render(fixture(), "w/main"))]
    assert lines[0].startswith(f"{esc(TEXT, OPEN)} {esc(f'1;{TEXT}', 'gadget')}")
    assert esc(GREEN, "1 done") in lines[0]
    assert esc(RED, "1 needs you") + esc(OVERLAY, " · ") + esc(PEACH, "1 working") in lines[3]
    assert lines[4].startswith(f"{esc(OVERLAY, '│')} {esc(f'1;{GREEN}', HERE)} {esc(TEXT, 'main')}")
    assert lines[4].endswith(esc(RED, FILL))
    assert lines[1].endswith(esc(GREEN, FILL))
    assert lines[7].endswith(esc(PEACH, FILL))
    assert lines[11].endswith(esc(GREEN, DOT))
    tree, words = esc(OVERLAY, "│   ├"), esc(SUBTEXT, "claude · win 1 · needs you")
    assert lines[5] == f"{tree} {esc(RED, FILL)} {words}"
    tree, words = esc(OVERLAY, "│   └"), esc(SUBTEXT, "teammate · win 2 · idle")
    assert lines[6] == f"{tree} {esc(GREEN, DOT)} {words}"
    assert lines[8].startswith(f"{tree} {esc(PEACH, FILL)} ")


def test_no_row_is_faint():
    """fzf's current-line background swallows faint text: a highlighted row would look blank."""
    for line in picker.lines(picker.render(fixture(), "w/main")):
        assert "\x1b[2;" not in line


def test_glyphs_are_written_as_escapes():
    for path in Path(picker.__file__).parent.rglob("*.py"):
        assert not re.search("[\ue000-\uf8ff]", path.read_text(encoding="utf-8")), path


def test_light_theme_rows(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_THEME", "light")
    lines = [line.split("\t")[2] for line in picker.lines(picker.render(fixture(), "w/main"))]
    assert lines[4].endswith(esc("38;2;210;15;57", FILL))
    assert lines[7].endswith(esc("38;2;254;100;11", FILL))
    assert esc("38;2;108;111;133", "claude · win 1 · working") in lines[8]


def test_long_names_stop_aligning_the_icons():
    long = "feat/" + "x" * 50
    found = Model(
        (Repo("/w", "w", "main", (worktree("w/long", long, "/w", (1, "lead", "done")),)),)
    )
    assert fields(picker.lines(picker.render(found, "")))[1][2] == f"│   {long}  {FILL}"


def test_git_status_sits_dim_between_the_branch_and_the_icon():
    rows = [
        worktree("w/main", "main", "/w", (1, "lead", "done")),
        worktree("w/feat", "feat/x", "/w"),
        worktree("w/zed", "zed", "/w", (1, "lead", "idle")),
        worktree("w/slow", "slow", "/w", (1, "lead", "working")),
    ]
    statuses = (Status(2, 13), Status(0, 1), Status(0, 0), None)
    rows = [dataclasses.replace(row, status=s) for row, s in zip(rows, statuses, strict=True)]
    lines = [
        line.split("\t")[2]
        for line in picker.lines(picker.render(Model((Repo("/w", "w", "main", tuple(rows)),)), ""))
    ]
    assert [plain(line) for line in lines if "claude" not in line] == [
        f"{OPEN} w  1 done · 1 working",
        f"│   main    ~2 ↑13  {FILL}",
        "│   feat/x  ↑1",
        f"│   zed             {DOT}",
        f"│   slow            {FILL}",
    ]
    assert esc(SUBTEXT, "~2 ↑13") in lines[1]
    assert esc(SUBTEXT, "↑1") in lines[3]


def test_keys(picking):
    stubs = picking
    stubs.fzf.reply(code=130)
    assert cli.main([]) == 130
    call = picked(stubs)
    args = call["args"]
    assert "--no-input" in args
    assert "--no-sort" in args
    assert "--delimiter=\t" in args
    assert "--with-nth=3" in args
    assert "--with-shell=sh -c" in args
    assert "--prompt=> " in args
    assert f"--header={header(HINTS)}" in args
    assert "--preview-window=right,60%,border-left,noinfo" in args
    assert not [arg for arg in args if arg.startswith("--color")]
    keys = bindings(args)
    assert args[args.index(KEYS) - 1] == "--bind"
    assert keys["/"] == f"show-input+unbind(j,k,/,q)+change-header:{header(SEARCH_HINTS)}"
    assert keys["enter"] == "transform:[ -n {1} ] && echo accept"
    assert keys["load"] == "pos(5)+unbind(load)"
    command = shlex.split(keys["tab"].removeprefix("transform:"))
    assert command[:4] == [sys.executable, "-m", "switchboard", "__fold"]
    assert command[5] == "{2}"
    assert fields(call["stdin"].splitlines()) == RENDERED


def test_the_theme_is_found_once_and_passed_to_fzf(picking, monkeypatch):
    """The preview runs under fzf, so it reads the picker's theme rather than finding its own."""
    stubs = picking
    monkeypatch.delenv("SWITCHBOARD_THEME")
    trigger = Path(os.environ["XDG_DATA_HOME"], "theme-monitor", "theme-change.trigger")
    trigger.parent.mkdir(parents=True)
    trigger.write_text("light\n")
    stubs.fzf.reply(code=130)
    cli.main([])
    assert os.environ["SWITCHBOARD_THEME"] == "light"
    assert esc("38;2;210;15;57", FILL) in picked(stubs)["stdin"]


def test_no_cursor_binding_without_the_current_session(picking):
    stubs = picking
    stubs.tmux.answer("display-message", stdout=f"{CLIENT}\tgone\n")
    stubs.fzf.reply(code=130)
    cli.main([])
    assert "load" not in bindings(picked(stubs)["args"])


@pytest.mark.parametrize(
    ("state", "out"),
    [
        (
            "enabled",
            f"clear-query+search()+hide-input+rebind(j,k,/,q)+change-header:{header(HINTS)}",
        ),
        ("hidden", "abort\n"),
    ],
)
def test_esc_leaves_a_search_else_closes(monkeypatch, state, out):
    esc_key = bindings(picker.fzf_args("/f", None))["esc"].removeprefix("transform:")
    monkeypatch.setenv("FZF_INPUT_STATE", state)
    assert sh(esc_key) == out


@pytest.mark.parametrize(("session", "out"), [("w/main", "accept\n"), ("", "")])
def test_enter_accepts_rows_but_not_headers(session, out):
    enter = bindings(picker.fzf_args("/f", None))["enter"].removeprefix("transform:")
    assert sh(enter.replace("{1}", shlex.quote(session))) == out


def test_enter_on_a_worktree_switches_the_pinned_client(picking, capsys):
    stubs = picking
    stubs.fzf.reply(line_of("w/feat/x"))
    assert cli.main([]) == 0
    assert switches(stubs) == [["switch-client", "-c", CLIENT, "-t", "=w/feat/x"]]
    assert capsys.readouterr() == ("", "")


def test_enter_on_an_agent_row_switches_to_its_session(picking):
    stubs = picking
    stubs.fzf.reply(line_of("gadget", 1))
    assert line_of("gadget", 1).startswith(f"gadget\t0\t│   └ {FILL} claude")
    assert cli.main([]) == 0
    assert switches(stubs) == [["switch-client", "-c", CLIENT, "-t", "=gadget"]]


def test_esc_exits_130_and_switches_nothing(picking):
    stubs = picking
    stubs.fzf.reply(code=130)
    assert cli.main([]) == 130
    assert switches(stubs) == []


@pytest.mark.parametrize(("stdout", "code"), [(f"\t1\t{OPEN} W tools/widget\n", 0), ("", 1)])
def test_a_line_without_a_session_switches_nothing(picking, stdout, code):
    stubs = picking
    stubs.fzf.reply(stdout, code=code)
    assert cli.main([]) == 0
    assert switches(stubs) == []


def test_the_temporary_folder_is_removed(picking, tmp_path):
    stubs = picking
    stubs.fzf.reply(code=130)
    cli.main([])
    command = shlex.split(bindings(picked(stubs)["args"])["tab"].removeprefix("transform:"))
    assert command[4].startswith(str(tmp_path / "switchboard-"))
    assert not list(tmp_path.glob("switchboard-*"))


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"code": 2}, "fzf exited with status 2"),
        ({"stdout": "w/zed\t1\t│   zed\n"}, "can't switch to w/zed"),
    ],
)
def test_failures(picking, capsys, answer, message):
    stubs = picking
    stubs.fzf.reply(answer.get("stdout", ""), code=answer.get("code", 0))
    stubs.tmux.answer("switch-client", code=1, stderr="can't find session\n")
    assert cli.main([]) == 1
    assert capsys.readouterr().err == f"switchboard: {message}\n"


def test_no_client(picking, capsys):
    stubs = picking
    stubs.tmux.answer("display-message", code=1, stderr="no current client\n")
    assert cli.main([]) == 1
    assert capsys.readouterr().err == "switchboard: can't find the tmux client to switch\n"
    assert [call["args"] for call in stubs.fzf.calls()] == [["--version"]]


@pytest.mark.parametrize(
    ("reply", "found"),
    [
        ({"stdout": "0.58.1 (brew)\n"}, "0.58.1"),
        ({"stdout": "0.9.0\n"}, "0.9.0"),
        ({"stdout": "devel\n"}, "devel"),
        ({"stdout": ""}, "none"),
        ({"code": 127}, "none"),
    ],
)
def test_fzf_too_old_or_missing(stubs, monkeypatch, capsys, reply, found):
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    stubs.fzf.reply(reply.get("stdout", ""), code=reply.get("code", 0))
    assert cli.main([]) == 1
    assert (
        capsys.readouterr().err
        == f"switchboard: the picker needs fzf 0.59 or newer; found {found}\n"
    )
    assert stubs.tmux.calls() == []


@pytest.mark.parametrize("version", ["0.59.0", "0.75.0 (Homebrew)", "0.60.0-devel", "1.0.0"])
def test_fzf_new_enough(stubs, version):
    stubs.fzf.reply(f"{version}\n")
    assert picker.fzf_problem() is None


def test_outside_tmux(stubs, capsys):
    assert cli.main([]) == 1
    assert capsys.readouterr() == ("", "switchboard: the picker only runs inside tmux\n")
    assert stubs.tmux.calls() == []
    assert stubs.fzf.calls() == []


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.delenv("FZF_QUERY", raising=False)
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / picker.MODEL).write_text(json.dumps(picker.render(fixture(), "w/main")))
    return str(folder)


def test_tab_folds_and_keeps_the_cursor_on_the_header(cache):
    rows = f"reload:{shlex.join([sys.executable, '-m', 'switchboard', '__rows', cache])}"
    assert picker.fold(cache, "1") == f"pos(4)+{rows}"
    assert fields(picker.rows(cache).splitlines()) == [
        *RENDERED[:3],
        ("", "1", f"{SHUT} W tools/widget  1 needs you · 1 working"),
        *RENDERED[10:],
    ]
    assert picker.fold(cache, "0") == f"pos(1)+{rows}"
    assert picker.fold(cache, "2") == f"pos(3)+{rows}"
    assert fields(picker.rows(cache).splitlines()) == [
        ("", "0", f"{SHUT} gadget  1 done"),
        ("", "1", f"{SHUT} W tools/widget  1 needs you · 1 working"),
        ("", "2", f"{SHUT} other"),
    ]
    picker.fold(cache, "0")
    assert picker.fold(cache, "1") == f"pos(4)+{rows}"
    assert fields(picker.rows(cache).splitlines()) == [*RENDERED[:10], ("", "2", f"{SHUT} other")]


def test_tab_while_searching_reloads_without_moving_the_cursor(cache, monkeypatch):
    monkeypatch.setenv("FZF_QUERY", "zed")
    assert picker.fold(cache, "1").startswith("reload:")


@pytest.mark.parametrize(("session", "out"), [("'w/main'", "w/main\n"), ("''", "")])
def test_the_preview_runs_through_its_hidden_command(stubs, session, out):
    stubs.tmux.answer("*", code=1, stderr="no server running\n")
    (command,) = [arg for arg in picker.fzf_args("/f", None) if arg.startswith("--preview=")]
    command = command.removeprefix("--preview=")
    assert shlex.split(command)[:4] == [sys.executable, "-m", "switchboard", "__preview"]
    assert plain(sh(command.replace("{1}", session))) == out


def test_tab_binding_runs_through_the_hidden_commands(cache):
    """fzf's side, done by hand: run the Tab binding, then the reload it asks for."""
    tab = bindings(picker.fzf_args(cache, None))["tab"].removeprefix("transform:")
    actions = sh(tab.replace("{2}", "'1'"))
    position, _, reload = actions.strip().partition("+reload:")
    assert position == "pos(4)"
    assert fields(sh(reload).splitlines())[3:5] == [
        ("", "1", f"{SHUT} W tools/widget  1 needs you · 1 working"),
        RENDERED[10],
    ]
