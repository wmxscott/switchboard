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

from switchboard import attention, cli, model, picker, sidebar
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
BACK = "clear-query+search()+hide-input+rebind(j,k,/,q)"


@pytest.fixture(autouse=True)
def dark(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_THEME", "dark")


def esc(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def fields(lines) -> list[tuple[str, ...]]:
    return [tuple(plain(line).split("\t")) for line in lines]


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


COMPACT = [
    ("", "0", f"{OPEN} gadget"),
    ("gadget", "0", f"│   main     {FILL}"),
    ("", "1", f"{OPEN} W tools/widget"),
    ("w/main", "1", f"│ {HERE} main     {FILL}"),
    ("w/feat/x", "1", f"│   feat/x   {FILL}"),
    ("w/zed", "1", "│   zed"),
    ("", "2", f"{OPEN} other"),
    ("scratch", "2", f"│   scratch  {DOT}"),
    ("home", "2", "│   home"),
]


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
    groups = picker.render(fixture(), "w/main", compact=True)
    assert fields(picker.lines(groups)) == COMPACT
    assert [group["title"] for group in groups] == ["gadget", "W tools/widget", "other"]
    lines = [line.split("\t")[2] for line in picker.lines(groups)]
    assert lines[0] == f"{esc(TEXT, OPEN)} {esc(f'1;{TEXT}', 'gadget')}"
    assert lines[3].startswith(f"{esc(OVERLAY, '│')} {esc(f'1;{GREEN}', HERE)} {esc(TEXT, 'main')}")
    assert lines[3].endswith(esc(RED, FILL))
    assert lines[4].endswith(esc(PEACH, FILL))
    assert lines[7].endswith(esc(GREEN, DOT))


def test_the_compact_list_cuts_long_names_short_to_keep_the_dots():
    long = "feat/" + "x" * 50
    found = Model(
        (Repo("/w", "w", "main", (worktree("w/long", long, "/w", (1, "lead", "done")),)),)
    )
    shown = fields(picker.lines(picker.render(found, "", compact=True)))[1][2]
    assert shown == f"│   {long[: picker.NARROW - 1]}…  {FILL}"
    assert fields(picker.lines(picker.render(found, "")))[1][2].startswith(f"│   {long}  ")


def test_the_picker_keeps_its_full_list():
    groups = picker.render(fixture(), "w/main")
    assert len(list(picker.lines(groups))) == len(COMPACT) + 5
    assert "~2 ↑13" in plain(groups[1]["rows"][0])


def test_a_folded_repo_shows_its_most_urgent_dot():
    plainer = Repo("/p", "plain", "main", (worktree("p", "main", "/p"),))
    found = Model((gadget(), widget(), plainer), fixture().other)
    groups = picker.render(found, "w/main", compact=True)
    shut = [line.split("\t")[2] for line in picker.lines(groups, folded=range(4))]
    assert [plain(line) for line in shut] == [
        f"{SHUT} gadget {FILL}",
        f"{SHUT} W tools/widget {FILL}",
        f"{SHUT} plain",
        f"{SHUT} other {DOT}",
    ]
    assert shut[0].endswith(f" {esc(GREEN, FILL)}")
    assert shut[1].endswith(f" {esc(RED, FILL)}")
    assert shut[3].endswith(f" {esc(GREEN, DOT)}")


def test_a_long_title_is_cut_short_to_keep_a_folded_repo_s_dot():
    long = "x" * 40
    found = Model(
        (Repo("/w", long, "main", (worktree("w/a", "main", "/w", (1, "lead", "done")),)),)
    )
    groups = picker.render(found, "", compact=True)
    shut = fields(picker.lines(groups, folded=[0]))[0][2]
    assert shut == f"{SHUT} {long[:22]}… {FILL}"
    assert len(shut) == 27
    assert fields(picker.lines(groups))[0][2] == f"{OPEN} {long[:22]}…"
    assert groups[0]["title"] == long
    assert fields(picker.lines(picker.render(found, "")))[0][2].startswith(f"{OPEN} {long}  ")


@pytest.fixture
def inside(stubs, monkeypatch, tmp_path):
    """Inside tmux in pane %5 of `w/main`, with fzf 0.59 and the fixture model."""
    monkeypatch.setenv("TMUX", "/tmp/stub,1,0")
    monkeypatch.setenv("TMUX_PANE", PANE)
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
    for arg in ("--no-input", "--no-sort", "--delimiter=\t", "--with-nth=3", "--no-info"):
        assert arg in args
    assert "--listen=127.0.0.1:0" in args
    assert not [arg for arg in args if arg.startswith(("--preview", "--color"))]
    keys = bindings(args)
    assert args[args.index("j:down,k:up,q:ignore") - 1] == "--bind"
    assert keys["/"] == "show-input+unbind(j,k,/,q)"
    assert keys["load"] == "pos(4)+unbind(load)"
    assert shlex.split(keys["start"].removeprefix("execute-silent:")) == [*SELF, "__listen"]
    enter = shlex.split(keys["enter,double-click"].removeprefix("transform:"))
    assert enter == [*SELF, "__switch", "{1}"]
    tab = shlex.split(keys["tab"].removeprefix("transform:"))
    assert tab[:4] == [*SELF, "__fold"]
    assert tab[5] == "{2}"
    assert fields(call["stdin"].splitlines()) == COMPACT


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
    key = bindings(sidebar.fzf_args("/f", None))["esc"].removeprefix("transform:")
    assert sh(key, FZF_INPUT_STATE=state) == out


def test_enter_switches_the_client_and_leaves_any_search(stubs):
    enter = bindings(sidebar.fzf_args("/f", None))["enter,double-click"]
    out = sh(enter.removeprefix("transform:").replace("{1}", "'w/feat/x'"), TMUX_PANE=PANE)
    assert out == BACK
    assert stubs.tmux.calls() == [["switch-client", "-t", "=w/feat/x"]]


def test_enter_on_a_header_does_nothing(stubs):
    enter = bindings(sidebar.fzf_args("/f", None))["enter,double-click"]
    assert sh(enter.removeprefix("transform:").replace("{1}", "''")) == ""
    assert stubs.tmux.calls() == []


def test_start_records_the_port_and_key_on_its_pane(stubs):
    start = bindings(sidebar.fzf_args("/f", None))["start"].removeprefix("execute-silent:")
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
    assert found["cache"] == [picker.FOLDED, picker.MODEL]
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


def test_redraw_rebuilds_the_list_and_keeps_folded_repos_folded(stubs, monkeypatch, tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / picker.MODEL).write_text(json.dumps(picker.render(fixture(), "", compact=True)))
    (folder / picker.FOLDED).write_text("[1]")
    alpha = Repo("/a", "alpha", "main", (worktree("alpha", "main", "/a", (1, "lead", "done")),))
    monkeypatch.setattr(model, "load", lambda: Model((alpha, gadget(), widget())))
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="alpha\n")
    out = sidebar.redraw(str(folder))
    assert fields(out.splitlines()) == [
        ("", "0", f"{OPEN} alpha"),
        ("alpha", "0", f"│ {HERE} main    {FILL}"),
        ("", "1", f"{OPEN} gadget"),
        ("gadget", "1", f"│   main    {FILL}"),
        ("", "2", f"{SHUT} W tools/widget {FILL}"),
    ]
    assert json.loads((folder / picker.FOLDED).read_text()) == [2]
    assert stubs.tmux.calls() == [["display-message", "-p", "-t", PANE, "#{session_name}"]]


def test_redraw_runs_through_its_hidden_command(stubs, monkeypatch, tmp_path):
    """fzf's side of a poke: the reload command, with the folder from fzf's environment."""
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("*", code=1, stderr="no server running\n")
    out = sh(shlex.join([*SELF, "__redraw"]), SWITCHBOARD_SIDEBAR=str(tmp_path))
    assert fields(out.splitlines()) == []
    assert json.loads((tmp_path / picker.MODEL).read_text()) == []


def test_redraw_from_a_fresh_folder_or_none(stubs, monkeypatch, tmp_path):
    monkeypatch.setattr(model, "load", fixture)
    monkeypatch.setenv("TMUX_PANE", PANE)
    stubs.tmux.answer("display-message", stdout="w/main\n")
    assert fields(sidebar.redraw(str(tmp_path)).splitlines()) == COMPACT
    assert sidebar.redraw("") == ""


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
    rows = [f"w/main\t0\t%{n}\tfzf\t\t\t\t\t\t{s}\n" for n, s in enumerate(sidebars)]
    agent = "w/main\t0\t%9\tclaude\tlead\tdone\t\t0\tclaude\t\n"
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
        "display-message", stdout="w/main\tlead\tworking\t\n/dev/ttys001\telsewhere\n"
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
