"""The sidebar, against the stub tmux and fzf, and a local listener standing in for fzf's."""

from __future__ import annotations

import itertools
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from switchboard import attention, cards, cli, model, picker, sidebar
from switchboard.git import Status, Worktree
from switchboard.model import Model, Repo, Row
from switchboard.projects import Label
from switchboard.tmux import Pane, Session

PANE = "%5"
SCRIPT = os.path.join(os.path.dirname(sys.executable), "switchboard")
SELF = [sys.executable, "-m", "switchboard"]
DOT, FILL, OPEN, SHUT, HERE = "\ueabc", "\uf111", "\uf0d7", "\uf0da", "\uf192"
TEXT, OVERLAY = "38;2;202;211;245", "38;2;128;135;162"
RED, GREEN, PEACH = "38;2;237;135;150", "38;2;166;218;149", "38;2;245;169;127"
BACK = "search()+hide-input+rebind(j,k,g,G,/,q)"


@pytest.fixture(autouse=True)
def dark(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_THEME", "dark")


def esc(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def fields(lines) -> list[tuple[str, ...]]:
    return [tuple(plain(line).split("\t")) for line in lines]


def items(text: str) -> list[str]:
    """fzf's `--read0` input, where every item ends with a NUL."""
    assert text == "" or text.endswith("\0")
    return text.split("\0")[:-1]


def worktree(name: str, branch: str, repo: str, *agents: tuple, status=None) -> Row:
    panes = tuple(Pane(name, window, f"%{window}", "claude", *state) for window, *state in agents)
    tree = Worktree(f"/src/{name}", branch, repo)
    return Row(Session(name, "", f"/src/{name}"), tree, panes, status)


def widget() -> Repo:
    return Repo(
        "/w/.bare",
        "widget",
        "main",
        (
            worktree(
                "w/main",
                "main",
                "/w",
                (1, "lead", "working", ("lead",)),
                (2, "teammate", "idle"),
                status=Status(2, 13),
            ),
            worktree("w/feat/x", "feat/x", "/w", (1, "lead", "working"), status=Status(0, 1)),
            worktree("w/zed", "zed", "/w"),
        ),
        Label("W", "tools/widget"),
    )


def gadget() -> Repo:
    return Repo(
        "/g/.git", "gadget", "main", (worktree("gadget", "main", "/g", (3, "lead", "done")),)
    )


def fixture() -> Model:
    other = (
        Row(Session("scratch", "", "/tmp"), None, (Pane("scratch", 4, "%9", "claude", "lead"),)),
        Row(Session("home", "", "/home"), None),
    )
    return Model((gadget(), widget()), other)


WIDTH = 29  # 32 columns, less fzf's pointer, marker and scrollbar


def edged(text: str, dot: str, width: int = WIDTH) -> str:
    """`text`, then `dot` in the last but one of `width` columns, or straight after `text` when
    there's no room."""
    return text.ljust(width - 2) + dot


LISTED = [
    ("", "", "0", f"{OPEN} gadget"),
    ("gadget", "%3", "0", "│   main     ", FILL),
    ("", "", "1", f"{OPEN} W tools/widget"),
    ("w/main", "%1", "1", f"│ {HERE} main     ", FILL),
    ("w/feat/x", "%1", "1", "│   feat/x   ", FILL),
    ("w/zed", "", "1", "│   zed"),
    ("", "", "2", f"{OPEN} other"),
    ("scratch", "%9", "2", "│   scratch  ", DOT),
    ("home", "", "2", "│   home"),
]


def compact(width: int = WIDTH) -> list[tuple[str, ...]]:
    """The compact list as the sidebar shows it in `width` columns."""
    return [(*item[:3], edged(*item[3:], width)) if item[4:] else item for item in LISTED]


COMPACT = compact()
SHUT_W = ("", "", "1", edged(f"{SHUT} W tools/widget ", FILL))
GADGET = ("gadget", "%3", "", "✓ gadget · claude\n  done")
W_MAIN = ("w/main", "%1", "", "▲ w/main · claude\n  needs you")


def gap(blank: int) -> tuple[str, ...]:
    return ("", "", cards.GAP, "\n" * blank + "─" * WIDTH)


@pytest.fixture
def sized(monkeypatch):
    """fzf's size, as it gives it to a reload."""
    monkeypatch.setenv("FZF_LINES", "20")
    monkeypatch.setenv("FZF_COLUMNS", "32")


def bindings(args: list[str]) -> dict[str, str]:
    found = {}
    for flag, value in itertools.pairwise(args):
        if flag == "--bind":
            key, _, action = value.partition(":")
            found[key] = action
    return found


def sh(command: str, **env: str) -> str:
    result = subprocess.run(
        ["sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **env},
    )
    assert result.stderr == ""
    return result.stdout


def test_the_compact_list_has_worktrees_and_their_dots_only():
    """Each dot is a field of its own, for the sidebar to place."""
    groups = picker.render(fixture(), "w/main", compact=True)
    assert fields(picker.lines(groups)) == LISTED
    assert [group["title"] for group in groups] == ["gadget", "W tools/widget", "other"]
    lines = [line.split("\t")[3:] for line in picker.lines(groups)]
    assert lines[0] == [f"{esc(TEXT, OPEN)} {esc(f'1;{TEXT}', 'gadget')}"]
    assert lines[3][0].startswith(
        f"{esc(OVERLAY, '│')} {esc(f'1;{GREEN}', HERE)} {esc(TEXT, 'main')}"
    )
    assert lines[3][1] == esc(RED, FILL)
    assert lines[4][1] == esc(PEACH, FILL)
    assert lines[7][1] == esc(GREEN, DOT)


def test_the_compact_list_cuts_long_names_short_to_keep_the_dots():
    long = "feat/" + "x" * 50
    found = Model(
        (Repo("/w", "w", "main", (worktree("w/long", long, "/w", (1, "lead", "done")),)),)
    )
    shown = fields(picker.lines(picker.render(found, "", compact=True)))[1][3:]
    assert shown == (f"│   {long[: picker.NARROW - 1]}…  ", FILL)
    assert fields(picker.lines(picker.render(found, "")))[1][3].startswith(f"│   {long}  ")


def test_the_picker_keeps_its_full_list():
    groups = picker.render(fixture(), "w/main")
    assert len(list(picker.lines(groups))) == len(COMPACT) + 5
    assert "~2 ↑13" in plain(groups[1]["rows"][0])


def test_a_folded_repo_shows_its_most_urgent_dot():
    plainer = Repo("/p", "plain", "main", (worktree("p", "main", "/p"),))
    found = Model((gadget(), widget(), plainer), fixture().other)
    groups = picker.render(found, "w/main", compact=True)
    shut = [line.split("\t")[3:] for line in picker.lines(groups, folded=range(4))]
    assert [[plain(part) for part in line] for line in shut] == [
        [f"{SHUT} gadget ", FILL],
        [f"{SHUT} W tools/widget ", FILL],
        [f"{SHUT} plain"],
        [f"{SHUT} other ", DOT],
    ]
    assert shut[0][1] == esc(GREEN, FILL)
    assert shut[1][1] == esc(RED, FILL)
    assert shut[3][1] == esc(GREEN, DOT)


def test_a_long_title_is_cut_short_to_keep_a_folded_repo_s_dot():
    long = "x" * 40
    found = Model(
        (Repo("/w", long, "main", (worktree("w/a", "main", "/w", (1, "lead", "done")),)),)
    )
    groups = picker.render(found, "", compact=True)
    shut = fields(picker.lines(groups, folded=[0]))[0][3:]
    assert shut == (f"{SHUT} {long[:22]}… ", FILL)
    assert fields(picker.lines(groups))[0][3] == f"{OPEN} {long[:22]}…"
    assert groups[0]["title"] == long
    assert fields(picker.lines(picker.render(found, "")))[0][3].startswith(f"{OPEN} {long}  ")


@pytest.fixture
def inside(stubs, monkeypatch, tmp_path):
    """Inside tmux in pane %5 of `w/main`, 30 rows of 32 columns, with fzf 0.59 and the fixture
    model."""
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    monkeypatch.setenv("TMUX_PANE", PANE)
    monkeypatch.setenv("LINES", "30")
    monkeypatch.setenv("COLUMNS", "32")
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    stubs.tmux.answer("display-message", stdout="w/main\n")
    stubs.fzf.reply("0.59.0\n")
    return stubs


def opened(stubs) -> dict:
    version, call = stubs.fzf.calls()
    assert version["args"] == ["--version"]
    return call


def test_keys_and_look(inside):
    stubs = inside
    stubs.fzf.reply(code=130)
    assert cli.main(["sidebar"]) == 130
    call = opened(stubs)
    args = call["args"]
    for arg in ("--no-input", "--no-sort", "--delimiter=\t", "--with-nth=4", "--no-info"):
        assert arg in args
    assert "--read0" in args
    assert "--listen=127.0.0.1:0" in args
    assert not [arg for arg in args if arg.startswith(("--preview", "--color"))]
    keys = bindings(args)
    assert args[args.index(sidebar.KEYS) - 1] == "--bind"
    assert keys["/"] == "show-input+clear-query+unbind(j,k,g,G,/,q)"
    assert shlex.split(keys["start"].removeprefix("execute-silent:")) == [*SELF, "__listen"]
    enter = shlex.split(keys["enter,double-click"].removeprefix("transform:"))
    assert enter == [*SELF, "__switch", "{1}", "{2}"]
    tab = shlex.split(keys["tab"].removeprefix("transform:"))
    assert tab[:4] == [*SELF, "__fold0"]
    assert tab[5] == "{3}"
    assert shlex.split(keys["resize"].removeprefix("reload:")) == [*SELF, "__rows0", tab[4]]
    assert fields(items(call["stdin"])) == [*COMPACT, gap(30 - 9 - 3), GADGET]


def test_the_current_line_is_highlighted_across_and_each_dot_keeps_off_its_edge(inside):
    """fzf fills the current item's lines to its `WIDTH` columns, and a dot sits in the last but
    one of them."""
    stubs = inside
    stubs.fzf.reply(code=130)
    cli.main(["sidebar"])
    call = opened(stubs)
    assert "--highlight-line" in call["args"]
    shown = [item[3] for item in fields(items(call["stdin"]))]
    assert shown[3] == f"│ {HERE} main{' ' * 19}{FILL}"
    dotted = [text for text in shown if text.endswith((FILL, DOT))]
    assert [len(text) for text in dotted] == [WIDTH - 1] * 4


def test_the_longest_name_and_title_keep_their_cuts_and_a_space_before_the_dot(tmp_path, sized):
    long = "x" * 40
    row = worktree("w/long", "feat/" + long, "/w", (1, "lead", "done"))
    groups = picker.render(Model((Repo("/w", long, "main", (row,)),)), "", compact=True)
    (tmp_path / picker.MODEL).write_text(json.dumps(groups))
    assert fields(items(sidebar.rows(str(tmp_path))))[1][3] == f"│   feat/{long[:14]}…   {FILL}"
    (tmp_path / picker.FOLDED).write_text("[0]")
    assert fields(items(sidebar.rows(str(tmp_path))))[0][3] == f"{SHUT} {long[:22]}…  {FILL}"


@pytest.mark.parametrize(("keys", "move"), [("j,down", "down"), ("k,up", "up")])
def test_j_and_k_step_over_the_gap(keys, move):
    """fzf's side: the move, then a transform on the item it lands on."""
    found = {key: (action, step) for key, action, step in STEPS.findall(sidebar.KEYS)}
    action, step = found[keys]
    assert action == move
    assert sh(step.replace("{3}", shlex.quote(cards.GAP))) == f"{move}\n"
    for group in ("1", ""):
        assert sh(step.replace("{3}", shlex.quote(group))) == ""
    assert sidebar.KEYS.endswith(",q:ignore")


STEPS = re.compile(r"(?:^|,)([a-z][a-z,]*):([a-z]+)\+transform\(([^)]*)\)")


def test_g_and_shift_g_jump_to_either_end_and_a_search_types_them():
    """fzf's `first` is the list's first row; `last` is the newest card, or the list's last row
    when there are no cards."""
    assert {"g:first", "G:last"} <= set(sidebar.KEYS.split(","))
    keys = bindings(sidebar.fzf_args("/f"))
    assert keys["/"] == "show-input+clear-query+unbind(j,k,g,G,/,q)"
    assert sh(keys["esc"].removeprefix("transform:"), FZF_INPUT_STATE="enabled") == BACK


def test_the_pickers_search_still_holds_only_its_own_keys():
    keys = bindings(picker.fzf_args("/f", None))
    assert keys["/"].startswith("show-input+clear-query+unbind(j,k,/,q)+")
    assert picker.back("") == "search()+hide-input+rebind(j,k,/,q)"


def test_with_no_cards_the_sidebar_is_the_list_alone(inside, monkeypatch):
    """No agent outside the sidebar's own session needs the user or is done."""
    stubs = inside
    stubs.fzf.reply(code=130)
    calm = Model((widget(),), fixture().other)
    monkeypatch.setattr(model, "load", lambda: calm)
    cli.main(["sidebar"])
    shown = fields(items(opened(stubs)["stdin"]))
    assert [item[3] for item in shown] == [item[3] for item in COMPACT[2:]]


def test_enter_on_a_card_lands_on_its_agents_pane(stubs, monkeypatch, sized, tmp_path):
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="w/main\n")
    *_, card = fields(items(sidebar.redraw(str(tmp_path))))
    assert card == GADGET
    assert enter(*card[:2]) == BACK
    assert stubs.tmux.calls()[-1] == ["switch-client", "-t", "%3"]


@pytest.mark.parametrize("group", ["", cards.GAP])
def test_tab_on_a_card_or_the_gap_folds_nothing(tmp_path, group):
    (tmp_path / picker.MODEL).write_text(json.dumps(picker.render(fixture(), "", compact=True)))
    tab = bindings(sidebar.fzf_args(str(tmp_path)))["tab"].removeprefix("transform:")
    assert sh(tab.replace("{3}", shlex.quote(group))).strip() == ""
    assert not (tmp_path / picker.FOLDED).exists()


def test_a_fold_or_a_resize_fits_the_stack_again(stubs, monkeypatch, sized, tmp_path):
    """fzf's side: Tab's reload and the resize's, each sized by fzf's rows and columns."""
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="w/main\n")
    sidebar.redraw(str(tmp_path))
    keys = bindings(sidebar.fzf_args(str(tmp_path)))
    resize = keys["resize"].removeprefix("reload:")
    assert fields(items(sh(resize))) == [*COMPACT, gap(20 - 9 - 3), GADGET]
    tab = keys["tab"].removeprefix("transform:")
    reload = sh(tab.replace("{3}", "'1'"), FZF_INPUT_STATE="hidden").partition("+reload:")[2]
    assert fields(items(sh(reload))) == [
        *COMPACT[:2],
        SHUT_W,
        *COMPACT[6:],
        gap(20 - 6 - 3),
        GADGET,
    ]
    narrow = compact(19)
    assert fields(items(sh(resize, FZF_LINES="8", FZF_COLUMNS="22"))) == [
        *narrow[:2],
        ("", "", "1", edged(f"{SHUT} W tools/widget ", FILL, 19)),
        *narrow[6:],
        ("", "", cards.GAP, "─" * 19),
        ("gadget", "%3", "", "✓ gadget · claude\n  done"),
    ]
    assert fields(items(sh(resize, FZF_COLUMNS="44")))[1][3] == edged("│   main", FILL, 41)
    assert fields(items(sh(resize, FZF_COLUMNS="16")))[1][3] == f"│   main     {FILL}"


def test_tab_folds_through_the_hidden_commands_and_reloads_nul_separated_items(tmp_path, sized):
    """fzf's side, done by hand: run the Tab binding, then the reload it asks for."""
    (tmp_path / picker.MODEL).write_text(json.dumps(picker.render(fixture(), "", compact=True)))
    tab = bindings(sidebar.fzf_args(str(tmp_path)))["tab"].removeprefix("transform:")
    actions = sh(tab.replace("{3}", "'1'"), FZF_INPUT_STATE="hidden")
    position, _, reload = actions.strip().partition("+reload:")
    assert position == "pos(3)"
    assert shlex.split(reload) == [*SELF, "__rows0", str(tmp_path)]
    assert fields(items(sh(reload))) == [*COMPACT[:2], SHUT_W, *COMPACT[6:]]


def test_no_key_closes_it(inside):
    stubs = inside
    stubs.fzf.reply(code=130)
    cli.main(["sidebar"])
    args = opened(stubs)["args"]
    assert not [arg for arg in args if "accept" in arg or "abort" in arg]


def test_no_hints_show_in_or_out_of_a_search(inside):
    stubs = inside
    stubs.fzf.reply(code=130)
    cli.main(["sidebar"])
    args = opened(stubs)["args"]
    assert not [arg for arg in args if arg.startswith("--header") or "change-header" in arg]


@pytest.mark.parametrize(
    ("state", "out"),
    [("enabled", BACK), ("hidden", "ignore\n")],
)
def test_esc_leaves_a_search_else_does_nothing(state, out):
    key = bindings(sidebar.fzf_args("/f"))["esc"].removeprefix("transform:")
    assert sh(key, FZF_INPUT_STATE=state) == out


def enter(session: str, pane: str) -> str:
    """Enter's binding, as fzf runs it on a line with `session` and `pane`."""
    binding = bindings(sidebar.fzf_args("/f"))["enter,double-click"]
    command = binding.removeprefix("transform:").replace("{1}", shlex.quote(session))
    return sh(command.replace("{2}", shlex.quote(pane)), TMUX_PANE=PANE)


def test_enter_lands_the_client_on_the_agents_pane_and_leaves_any_search(stubs):
    assert enter("w/feat/x", "%1") == BACK
    assert stubs.tmux.calls() == [["switch-client", "-t", "%1"]]


def test_enter_on_a_session_without_agents_switches_to_it(stubs):
    assert enter("w/zed", "") == BACK
    assert stubs.tmux.calls() == [["switch-client", "-t", "=w/zed"]]


def test_enter_on_a_pane_gone_since_falls_back_to_its_session(stubs):
    stubs.tmux.answer("switch-client -t %1", code=1, stderr="can't find pane: %1\n")
    assert enter("w/feat/x", "%1") == BACK
    assert stubs.tmux.calls() == [
        ["switch-client", "-t", "%1"],
        ["switch-client", "-t", "=w/feat/x"],
    ]


def test_enter_on_a_header_does_nothing(stubs):
    assert enter("", "") == ""
    assert stubs.tmux.calls() == []


def test_start_records_the_port_and_key_on_its_pane(stubs):
    start = bindings(sidebar.fzf_args("/f"))["start"].removeprefix("execute-silent:")
    assert sh(start, TMUX_PANE=PANE, FZF_PORT="53122", FZF_API_KEY="k3y") == ""
    assert stubs.tmux.calls() == [
        ["set-option", "-p", "-t", PANE, "@switchboard-sidebar", "53122 k3y"]
    ]


# An `fzf` that keeps what the sidebar gave it: some of its environment, the files in the
# sidebar's folder, and its input.
SPY = """#!{python}
import json, os, sys

if sys.argv[1:] == ["--version"]:
    print("0.59.0")
    sys.exit(0)
folder = os.environ.get("SWITCHBOARD_SIDEBAR", "")
names = ("FZF_API_KEY", "SWITCHBOARD_SIDEBAR", "SWITCHBOARD_THEME")
found = {{
    "env": {{name: os.environ[name] for name in names if name in os.environ}},
    "cache": os.path.isdir(folder) and sorted(os.listdir(folder)),
    "stdin": sys.stdin.read(),
}}
with open({seen!r}, "w") as out:
    json.dump(found, out)
sys.exit(130)
"""


def test_fzf_gets_an_api_key_and_the_folder_but_not_the_theme(inside, monkeypatch, tmp_path):
    """Each reload finds the theme again, so a long-lived sidebar follows it."""
    monkeypatch.delenv("SWITCHBOARD_THEME")
    trigger = Path(os.environ["XDG_DATA_HOME"], "theme-monitor", "theme-change.trigger")
    trigger.parent.mkdir(parents=True)
    trigger.write_text("light\n")
    seen = tmp_path / "seen.json"
    (tmp_path / "bin" / "fzf").write_text(SPY.format(python=sys.executable, seen=str(seen)))
    assert cli.main(["sidebar"]) == 130
    found = json.loads(seen.read_text())
    assert set(found["env"]) == {"FZF_API_KEY", "SWITCHBOARD_SIDEBAR"}
    assert re.fullmatch("[0-9a-f]{32}", found["env"]["FZF_API_KEY"])
    assert found["cache"] == sorted(
        [sidebar.CARDS, picker.FOLDED, picker.MODEL, sidebar.SHOWN, sidebar.NEXT, sidebar.MOVES]
    )
    assert esc("38;2;210;15;57", FILL) in found["stdin"]


def test_on_exit_it_unsets_its_pane_option_and_removes_its_folder(inside, tmp_path):
    stubs = inside
    stubs.fzf.reply(code=130)
    cli.main(["sidebar"])
    assert stubs.tmux.calls()[-1] == ["set-option", "-p", "-u", "-t", PANE, "@switchboard-sidebar"]
    assert not list(tmp_path.glob("switchboard-*"))


@pytest.mark.parametrize("code", [0, 1])
def test_fzf_ending_otherwise_ends_the_sidebar_quietly(inside, capsys, code):
    stubs = inside
    stubs.fzf.reply(code=code)
    assert cli.main(["sidebar"]) == code
    assert capsys.readouterr() == ("", "")
    assert not [call for call in stubs.tmux.calls() if call[0] == "switch-client"]


def test_an_fzf_error_is_reported(inside, capsys):
    stubs = inside
    stubs.fzf.reply(code=2)
    assert cli.main(["sidebar"]) == 1
    assert capsys.readouterr().err == "switchboard: fzf exited with status 2\n"


@pytest.mark.parametrize("env", [{}, {"TMUX": "/tmp/stub,1,0"}, {"TMUX_PANE": PANE}])
def test_outside_a_tmux_pane(stubs, monkeypatch, capsys, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["sidebar"]) == 1
    assert capsys.readouterr() == ("", "switchboard: the sidebar only runs inside tmux\n")
    assert stubs.tmux.calls() == []
    assert stubs.fzf.calls() == []


def test_fzf_too_old(stubs, monkeypatch, capsys):
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.fzf.reply("0.58.1\n")
    assert cli.main(["sidebar"]) == 1
    message = "the sidebar needs fzf 0.59 or newer; found 0.58.1"
    assert capsys.readouterr().err == f"switchboard: {message}\n"


def test_redraw_rebuilds_the_list_and_keeps_folded_repos_folded(
    stubs, monkeypatch, sized, tmp_path
):
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / picker.MODEL).write_text(json.dumps(picker.render(fixture(), "", compact=True)))
    (folder / picker.FOLDED).write_text("[1]")
    alpha = Repo("/a", "alpha", "main", (worktree("alpha", "main", "/a", (1, "lead", "done")),))
    monkeypatch.setattr(model, "load", lambda: Model((alpha, gadget(), widget())))
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="alpha\n")
    out = sidebar.redraw(str(folder))
    assert fields(items(out)) == [
        ("", "", "0", f"{OPEN} alpha"),
        ("alpha", "%1", "0", edged(f"│ {HERE} main", FILL)),
        ("", "", "1", f"{OPEN} gadget"),
        ("gadget", "%3", "1", edged("│   main", FILL)),
        ("", "", "2", edged(f"{SHUT} W tools/widget", FILL)),
        gap(20 - 5 - 5),
        GADGET,
        W_MAIN,
    ]
    assert json.loads((folder / picker.FOLDED).read_text()) == [2]
    assert stubs.tmux.calls() == [["display-message", "-p", "-t", PANE, "#{session_name}"]]


def test_redraw_runs_through_its_hidden_command(stubs, monkeypatch, tmp_path):
    """fzf's side of a poke: the reload command, with the folder from fzf's environment."""
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("*", code=1, stderr="no server running\n")
    out = sh(shlex.join([*SELF, "__redraw"]), SWITCHBOARD_SIDEBAR=str(tmp_path))
    assert items(out) == []
    assert json.loads((tmp_path / picker.MODEL).read_text()) == []


def test_redraw_from_a_fresh_folder_or_none(stubs, monkeypatch, sized, tmp_path):
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="w/main\n")
    assert fields(items(sidebar.redraw(str(tmp_path)))) == [*COMPACT, gap(20 - 9 - 3), GADGET]
    assert sidebar.redraw("") == ""


def land(folder: str, at: int, **env: str) -> str:
    """fzf's load binding, run as fzf runs it once a list lands, with the cursor on row `at`."""
    load = bindings(sidebar.fzf_args(folder))["load"].removeprefix("transform:")
    return sh(load, SWITCHBOARD_SIDEBAR=folder, FZF_POS=str(at), **env)


def moved(folder: str, at: int, count: int) -> int:
    """The cursor's row once a list of `count` items lands with it on row `at`, which fzf first
    cuts to the list's last."""
    at = min(at, count)
    actions = land(folder, at)
    return int(actions.removeprefix("pos(").removesuffix(")\n")) if actions else at


def poked(monkeypatch, folder: str, found: Model, at: int) -> tuple[list[tuple[str, ...]], int]:
    """fzf's side of a poke, with the cursor on row `at`: the items it reloads, and the cursor's
    row once they land."""
    monkeypatch.setattr(model, "load", lambda: found)
    monkeypatch.setenv("FZF_POS", str(at))
    shown = fields(items(sidebar.redraw(folder)))
    return shown, moved(folder, at, len(shown))


def sessions(*named: tuple[str, int, str]) -> Model:
    """One repo with a session for each `(name, window, state)`, its lead agent in that window
    `done`, needing you, or `idle`."""
    turn = {"done": ("done",), "needs": ("working", ("lead",)), "idle": ("idle",)}
    found = (worktree(name, name, "/r", (n, "lead", *turn[state])) for name, n, state in named)
    return Model((Repo("/r", "r", "main", tuple(found)),))


@pytest.fixture
def folder(stubs, monkeypatch, sized, tmp_path) -> str:
    """The folder of session `a`'s sidebar."""
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="a\n")
    return str(tmp_path)


TWO = (("a", 1, "idle"), ("b", 2, "done"))
GROWN = (("a", 1, "idle"), ("a2", 5, "idle"), ("b", 2, "done"), ("c", 3, "needs"))


def test_the_cursor_keeps_its_card_or_row_when_a_card_and_a_row_arrive(folder, monkeypatch):
    shown, _ = poked(monkeypatch, folder, sessions(*TWO), 1)
    assert [item[:3] for item in shown[3:]] == [("", "", cards.GAP), ("b", "%2", "")]
    shown, at = poked(monkeypatch, folder, sessions(*GROWN), 5)
    assert (at, shown[at - 1][:3]) == (7, ("b", "%2", ""))
    shown, at = poked(monkeypatch, folder, sessions(("a0", 6, "idle"), *GROWN), 4)
    assert (at, shown[at - 1][:3]) == (5, ("b", "%2", "0"))


FOUR = (("a", 1, "idle"), ("b", 2, "done"), ("c", 3, "needs"), ("d", 4, "needs"))


@pytest.mark.parametrize(
    ("on", "resolved", "lands"),
    [
        (9, "b", ("d", "%4", "")),  # an older card goes: the cursor keeps its own
        (8, "c", ("d", "%4", "")),  # its card goes: the newer one that takes its place
        (9, "d", ("c", "%3", "")),  # the newest goes: the one before it
        (8, "bcd", ("d", "%4", "0")),  # no cards left: the list's last row
    ],
)
def test_a_card_resolving_leaves_the_cursor_on_the_nearest_card(
    folder, monkeypatch, on, resolved, lands
):
    shown, _ = poked(monkeypatch, folder, sessions(*FOUR), 1)
    assert [item[1] for item in shown[6:]] == ["%2", "%3", "%4"]
    left = [(name, n, "idle" if name in resolved else state) for name, n, state in FOUR]
    shown, at = poked(monkeypatch, folder, sessions(*left), on)
    assert shown[at - 1][:3] == lands


def test_a_header_keeps_the_cursor_by_its_title_when_a_repo_arrives_above(folder, monkeypatch):
    poked(monkeypatch, folder, fixture(), 1)
    alpha = Repo("/a", "alpha", "main", (worktree("alpha", "main", "/a"),))
    shown, at = poked(monkeypatch, folder, Model((alpha, gadget(), widget()), fixture().other), 3)
    assert (at, shown[at - 1][2:]) == (5, ("2", f"{OPEN} W tools/widget"))


def test_a_resize_keeps_the_cursor_on_its_card_or_the_nearest_shown(folder, monkeypatch):
    poked(monkeypatch, folder, sessions(*FOUR), 1)
    resize = bindings(sidebar.fzf_args(folder))["resize"].removeprefix("reload:")
    for on in (9, 7):
        short = fields(items(sh(resize, FZF_LINES="9", FZF_POS=str(on))))
        assert short[5:7] == [gap(0), ("", "", "", "+2 more")]
        at = moved(folder, on, len(short))
        assert short[at - 1][1] == "%4"
        sh(resize, FZF_POS=str(at))
        assert moved(folder, at, 9) == 9
    short = fields(items(sh(resize, FZF_LINES="9", FZF_POS="1")))
    moved(folder, 1, len(short))
    tall = fields(items(sh(resize, FZF_POS="7")))
    assert tall[moved(folder, 7, len(tall)) - 1][1] == "%2"


# An `fzf` that runs its load binding as fzf does once its input has landed, with the cursor on
# the first row, and keeps what it prints.
LANDS = """#!{python}
import os, subprocess, sys

if sys.argv[1:] == ["--version"]:
    print("0.59.0")
    sys.exit(0)
sys.stdin.read()
args = sys.argv[1:]
load = next(b for f, b in zip(args, args[1:]) if f == "--bind" and b.startswith("load:"))
env = {{**os.environ, "FZF_POS": "1"}}
out = subprocess.run(
    ["sh", "-c", load.removeprefix("load:transform:")], env=env, capture_output=True, text=True
)
with open({seen!r}, "w") as f:
    f.write(out.stdout + out.stderr)
sys.exit(130)
"""


def test_the_first_draw_puts_the_cursor_on_the_current_session(inside, tmp_path):
    seen = tmp_path / "seen.txt"
    (tmp_path / "bin" / "fzf").write_text(LANDS.format(python=sys.executable, seen=str(seen)))
    assert cli.main(["sidebar"]) == 130
    assert seen.read_text() == "pos(4)\n"


def test_tab_keeps_the_cursor_on_the_folded_header_once_the_list_lands(folder, monkeypatch):
    poked(monkeypatch, folder, fixture(), 1)
    tab = bindings(sidebar.fzf_args(folder))["tab"].removeprefix("transform:")
    actions = sh(tab.replace("{3}", "'1'"), FZF_INPUT_STATE="hidden", FZF_POS="5")
    position, _, reload = actions.strip().partition("+reload:")
    assert position == "pos(3)"
    shown = fields(items(sh(reload, FZF_POS="3")))
    assert shown[moved(folder, 3, len(shown)) - 1] == SHUT_W


def test_a_list_moves_the_cursor_once_and_never_while_a_search_filters_it(folder, monkeypatch):
    poked(monkeypatch, folder, sessions(*TWO), 1)
    monkeypatch.setattr(model, "load", lambda: sessions(("a0", 6, "idle"), ("a", 1, "idle")))
    monkeypatch.setenv("FZF_POS", "2")
    sidebar.redraw(folder)
    assert land(folder, 2, FZF_INPUT_STATE="enabled", FZF_QUERY="a") == ""
    assert land(folder, 2) == ""
    sidebar.redraw(folder)
    assert land(folder, 2, FZF_INPUT_STATE="hidden", FZF_QUERY="a") == "pos(2)\n"


X, Y, MORE, GAP = ("row", "x"), ("row", "y"), ("more",), (cards.GAP,)
C1, C3, C4 = ("card", "%1"), ("card", "%3"), ("card", "%4")


@pytest.mark.parametrize(
    ("new", "lands"),
    [
        ([X, GAP, C4], [C4, C4]),  # `+N more` and its card gone: the first card, the newest
        ([X, Y, GAP, C1, C3], [C1, C3]),  # `+N more` unfolds: the first card
        ([X, Y], [Y, Y]),  # no cards: the list's last row
    ],
)
def test_more_or_a_card_gone_moves_the_cursor_to_a_card_never_the_gap(new, lands):
    assert [new[n] for n in sidebar.steady([X, GAP, MORE, C3], new)[2:]] == lands


def test_a_row_gone_gives_the_cursor_the_next_row_else_the_one_before():
    old = [("head", "r"), X, Y, ("head", "s"), ("row", "z")]
    assert sidebar.steady(old, [("head", "r"), X, ("head", "s"), ("row", "z")])[2] == 2
    assert sidebar.steady(old, [("head", "r"), X])[2:] == [1, 1, 1]


class Listener:
    """A local port that keeps whatever each connection sends."""

    def __init__(self):
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.received: list[bytes] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(4096):
                    data += chunk
                self.received.append(data)

    def requests(self, count: int) -> list[bytes]:
        deadline = time.monotonic() + 5
        while len(self.received) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.received

    def close(self):
        self.server.close()


@pytest.fixture
def listener():
    found = Listener()
    yield found
    found.close()


def dead_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as server:
        return server.getsockname()[1]


def test_poke_posts_a_reload_with_the_api_key(listener):
    sidebar.poke([f"{listener.port} k3y"])
    (request,) = listener.requests(1)
    head, _, body = request.decode().partition("\r\n\r\n")
    first, *headers = head.split("\r\n")
    assert first == "POST / HTTP/1.1"
    assert "x-api-key: k3y" in headers
    assert f"content-length: {len(body.encode())}" in headers
    assert shlex.split(body.removeprefix("reload:")) == [*SELF, "__redraw"]


def test_poke_skips_dead_and_broken_endpoints_without_waiting(listener):
    start = time.perf_counter()
    endpoints = [f"{dead_port()} k", "", "junk", sidebar.STARTING, "99999 k", "-1 k"]
    sidebar.poke([*endpoints, f"{listener.port} k"])
    assert time.perf_counter() - start < 1
    assert len(listener.requests(1)) == 1


def panes(stubs, *sidebars: str) -> None:
    rows = [f"w/main\t0\t{n}\t%{n}\tfzf\t\t\t\t\t\t\t\t\t\t{s}\n" for n, s in enumerate(sidebars)]
    agent = "w/main\t0\t0\t%9\tclaude\tlead\tdone\t\t0\tclaude\t\t\t\t\t\n"
    stubs.tmux.answer("list-sessions", stdout="w/main\t\t/w\t0\t\nother\t\t/o\t0\t\n")
    stubs.tmux.answer("list-panes", stdout=agent + "".join(rows))


def test_refresh_pokes_each_sidebar(stubs, listener):
    other = Listener()
    try:
        panes(stubs, f"{listener.port} a", "", f"{other.port} b")
        attention.refresh()
        assert len(listener.requests(1)) == 1
        assert len(other.requests(1)) == 1
    finally:
        other.close()
    assert b"x-api-key: a\r\n" in listener.received[0]
    assert b"x-api-key: b\r\n" in other.received[0]


def test_seen_pokes_sidebars_too(stubs, listener):
    panes(stubs, f"{listener.port} a")
    attention.seen("w/main")
    assert len(listener.requests(1)) == 1


def test_refresh_without_a_sidebar_does_no_more(stubs, monkeypatch):
    poked = []
    monkeypatch.setattr(sidebar, "poke", poked.append)
    panes(stubs, "", "")
    attention.refresh()
    assert poked == []
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions", "list-panes", "set-option"]


def test_a_dead_sidebar_leaves_refresh_and_the_hook_silent(stubs):
    panes(stubs, f"{dead_port()} k", "junk")
    stubs.tmux.answer(
        "display-message", stdout="w/main\tlead\tworking\t\t\t\t\n/dev/ttys001\t\telsewhere\n"
    )
    for args, stdin in ((["refresh"], ""), (["hook", "Stop"], '{"hook_event_name": "Stop"}')):
        start = time.perf_counter()
        result = subprocess.run(
            [SCRIPT, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "TMUX_PANE": "%9"},
        )
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert time.perf_counter() - start < 3
    assert [call[0] for call in stubs.tmux.calls()].count("list-panes") == 2


LIST = [
    "list-panes",
    "-F",
    "#{pane_id}\t#{@switchboard-sidebar}\t#{@switchboard-layout}\t#{window_layout}",
    "-t",
]
LAUNCH = ["sh", "-c", f"{shlex.join([*SELF, 'sidebar'])}; exit"]
SPLIT = ["split-window", "-hbdf", "-l", "32", "-P", "-F", "#{pane_id}", "-t"]


def layout(*panes: dict, w: int = 40) -> str:
    """A tmux 3.8 layout of `panes` side by side, each `w` wide."""
    cells = [
        {"t": "p", "w": w, "h": 40, "x": (w + 1) * n, "y": 0, **p} for n, p in enumerate(panes)
    ]
    return json.dumps({"V": 2, "L": {"t": "h", "w": 120, "h": 40, "x": 0, "y": 0, "c": cells}})


BEFORE = layout({"I": PANE, "a": True}, {"I": "%6", "l": 0})
TAG = [
    *("set-option", "-p", "-t", "%8", "@switchboard-layout", BEFORE, ";"),
    *("set-option", "-p", "-o", "-q", "-t", "%8", "@switchboard-sidebar", "starting"),
]


@pytest.fixture
def window(stubs, monkeypatch):
    """Inside tmux in pane %5, in a window with another pane and no sidebar."""
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("list-panes", stdout=f"{PANE}\t\t\t{BEFORE}\n%6\t\t\t{BEFORE}\n")
    stubs.tmux.answer("split-window", stdout="%8\n")
    return stubs


def test_toggle_opens_a_sidebar_down_the_left_and_tags_it_quietly(window, capsys):
    """Its tag, and the window's layout before it, for closing it to put back."""
    assert cli.main(["sidebar", "--toggle"]) == 0
    assert capsys.readouterr() == ("", "")
    assert window.tmux.calls() == [[*LIST, PANE], [*SPLIT, PANE, *LAUNCH], TAG]


NOW = layout({"I": "%8", "a": True}, {"I": PANE, "l": 1}, {"I": "%6", "l": 0}, w=26)
AFTER = layout({"I": PANE, "l": 0}, {"I": "%6", "a": True}, w=30)


def closing(saved: str) -> str:
    return f"%8\tstarting\t{saved}\t{NOW}\n{PANE}\t\t\t{NOW}\n%6\t\t\t{NOW}\n"


def kill(sidebar: str) -> list[str]:
    """Closes it, and asks for the layout, focus and last-pane history tmux leaves without it."""
    return [
        "kill-pane",
        "-t",
        sidebar,
        ";",
        "display-message",
        "-p",
        "-t",
        PANE,
        "#{window_layout}",
    ]


@pytest.mark.parametrize("tag", [sidebar.STARTING, "53122 k3y"])
def test_toggle_closes_the_sidebar_in_its_window(window, capsys, tag):
    window.tmux.answer("list-panes", stdout=f"%3\t{tag}\t\t{NOW}\n{PANE}\t\t\t{NOW}\n")
    assert cli.main(["sidebar", "--toggle"]) == 0
    assert capsys.readouterr() == ("", "")
    assert window.tmux.calls() == [[*LIST, PANE], kill("%3")]


def test_closing_puts_back_the_widths_it_took_but_keeps_the_focus(window, capsys):
    """The layout from before it opened, with the focus and last-pane history tmux leaves once it
    has closed, which moves the focus off a sidebar that had it."""
    window.tmux.answer("list-panes", stdout=closing(BEFORE))
    window.tmux.answer("kill-pane", stdout=AFTER + "\n")
    assert cli.main(["sidebar", "--toggle", "%8"]) == 0
    assert capsys.readouterr() == ("", "")
    restored = json.loads(window.tmux.calls()[2][-1])
    assert window.tmux.calls()[1:] == [
        kill("%8"),
        ["select-layout", "-t", PANE, json.dumps(restored, separators=(",", ":"))],
    ]
    assert restored == json.loads(layout({"I": PANE, "l": 0}, {"I": "%6", "a": True}))


@pytest.mark.parametrize("saved", ["", "not a layout", "{}"])
def test_closing_without_a_layout_to_put_back_only_closes(window, saved):
    window.tmux.answer("list-panes", stdout=closing(saved))
    window.tmux.answer("kill-pane", stdout=AFTER + "\n")
    assert cli.main(["sidebar", "--toggle"]) == 0
    assert window.tmux.calls()[1:] == [kill("%8")]


def test_a_layout_that_no_longer_fits_is_left_alone(window, capsys):
    """tmux refuses a layout whose panes have changed since."""
    window.tmux.answer("list-panes", stdout=closing(BEFORE))
    window.tmux.answer("kill-pane", stdout=AFTER + "\n")
    window.tmux.answer("select-layout", code=1, stderr="have 3 panes but need 2\n")
    assert cli.main(["sidebar", "--toggle"]) == 0
    assert capsys.readouterr() == ("", "")


def test_toggle_takes_the_pane_from_a_key_binding(window, monkeypatch):
    """`run-shell` sets `$TMUX` but not `$TMUX_PANE`, so the binding passes `#{pane_id}`."""
    monkeypatch.delenv("TMUX_PANE")
    assert cli.main(["sidebar", "--toggle", "%2"]) == 0
    assert window.tmux.calls() == [[*LIST, "%2"], [*SPLIT, "%2", *LAUNCH], TAG]


def test_a_failed_split_tags_nothing(window, capsys):
    window.tmux.answer("split-window", code=1, stderr="no space for new pane\n")
    assert cli.main(["sidebar", "--toggle"]) == 1
    assert capsys.readouterr() == ("", "switchboard: can't open the sidebar\n")
    assert window.tmux.calls() == [[*LIST, PANE], [*SPLIT, PANE, *LAUNCH]]


def test_toggle_reports_a_pane_it_cant_find_or_close(window, capsys):
    window.tmux.answer("list-panes", code=1, stderr="can't find pane: %2\n")
    assert cli.main(["sidebar", "--toggle", "%2"]) == 1
    assert capsys.readouterr().err == "switchboard: can't find pane %2\n"
    window.tmux.answer("list-panes", stdout="%3\tstarting\n")
    window.tmux.answer("kill-pane", code=1)
    assert cli.main(["sidebar", "--toggle"]) == 1
    assert capsys.readouterr().err == "switchboard: can't close the sidebar\n"


@pytest.mark.parametrize(
    ("env", "args"), [({}, []), ({"TMUX_PANE": PANE}, []), ({}, ["%2"]), ({"TMUX": "/s,1,0"}, [])]
)
def test_toggle_outside_tmux(stubs, monkeypatch, capsys, env, args):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["sidebar", "--toggle", *args]) == 1
    assert capsys.readouterr() == ("", "switchboard: the sidebar only runs inside tmux\n")
    assert stubs.tmux.calls() == []


def test_the_new_pane_runs_the_sidebar_and_ends_with_it(window):
    """By the same executable, under a shell that stays its parent, as tmux-resurrect saves it."""
    cli.main(["sidebar", "--toggle"])
    launch = window.tmux.calls()[1][-3:]
    window.fzf.reply("0.59.0\n")
    window.fzf.reply(code=130)
    result = subprocess.run(launch, capture_output=True, text=True, timeout=30, env=os.environ)
    assert (result.returncode, result.stderr) == (130, "")
    assert "--listen=127.0.0.1:0" in window.fzf.calls()[1]["args"]
