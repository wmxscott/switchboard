"""The picker: tmux sessions in fzf, grouped by repo with their agents, switching the client that
opened it.

Each fzf line is `session<TAB>group<TAB>display`, with only the display shown. A repo header has no
session. Folding reloads the lines from a cache in a temporary folder, so it never re-runs git.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from switchboard import panestate as ps
from switchboard import run

if TYPE_CHECKING:
    from switchboard.model import Model, Row
    from switchboard.tmux import Pane

MIN_FZF = (0, 59)
KEYS = "j:down,k:up,/:show-input+unbind(j,k,/)"
HINT = "j/k move · / search · tab fold · enter switch · esc close"
COLOURS = "16,pointer:cyan,header:bright-black,info:bright-black,prompt:cyan,border:bright-black"
LOOK = ("--layout=reverse", "--height=100%", "--border=none", "--margin=0", "--padding=0")
PREVIEW = "right,45%,border-left,noinfo"

ICON = {ps.NEEDS: "▲", ps.DONE: "✓", ps.WORKING: "●", ps.IDLE: "○"}
WORD = {ps.NEEDS: "needs you", ps.DONE: "done", ps.WORKING: "working", ps.IDLE: "idle"}
SGR = {ps.NEEDS: "33", ps.DONE: "32", ps.WORKING: "34", ps.IDLE: "90"}
SUMMED = (ps.NEEDS, ps.DONE, ps.WORKING)
BOLD, DIM, CYAN = "1", "90", "36"
WIDTH = 40

MODEL, FOLDED = "model.json", "folded.json"

Group = dict[str, Any]


class PickerError(Exception):
    pass


def pick() -> int:
    if not os.environ.get("TMUX"):
        raise PickerError("the picker only runs inside tmux")
    problem = fzf_problem()
    if problem:
        raise PickerError(problem)
    client, current = pinned()
    if not client:
        raise PickerError("can't find the tmux client to switch")
    from switchboard import model

    groups = render(model.load(), current)
    folder = tempfile.mkdtemp(prefix="switchboard-")
    try:
        Path(folder, MODEL).write_text(json.dumps(groups), encoding="utf-8")
        result = subprocess.run(
            ["fzf", *fzf_args(folder, cursor(groups, current))],
            input="".join(f"{line}\n" for line in lines(groups)),
            stdout=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if result.returncode == 130:
        return 130
    if result.returncode not in (0, 1):
        raise PickerError(f"fzf exited with status {result.returncode}")
    session = result.stdout.partition("\t")[0]
    if session and run.tmux(("switch-client", "-c", client, "-t", f"={session}")) is None:
        raise PickerError(f"can't switch to {session}")
    return 0


def fzf_problem() -> str | None:
    words = (run.output("fzf", "--version") or "").split()
    found = words[0] if words else "none"
    parts = found.split(".")
    numbers = [int(part) for part in parts[:2] if part.isdecimal()]
    if len(numbers) == 2 and tuple(numbers) >= MIN_FZF:
        return None
    return f"the picker needs fzf {'.'.join(map(str, MIN_FZF))} or newer; found {found}"


def pinned() -> tuple[str, str]:
    """The client and its session, read once: later, tmux's idea of the current client can move."""
    out = run.output("tmux", "display-message", "-p", "#{client_name}\t#{session_name}")
    client, _, session = (out or "").removesuffix("\n").partition("\t")
    return client, session


def fzf_args(folder: str, at: int | None) -> list[str]:
    fold = shlex.join([*_self(), "__fold", folder])
    preview = shlex.join([*_self(), "__preview"])
    args = [
        "--ansi",
        "--no-sort",
        *LOOK,
        "--no-info",
        "--no-input",
        "--bind",
        KEYS,
        "--delimiter=\t",
        "--with-nth=3",
        "--with-shell=sh -c",
        f"--color={COLOURS}",
        f"--header={HINT}",
        f"--preview={preview} {{1}}",
        f"--preview-window={PREVIEW}",
        "--bind",
        "enter:transform:[ -n {1} ] && echo accept",
        "--bind",
        f"tab:transform:{fold} {{2}}",
    ]
    if at:
        args += ["--bind", f"load:pos({at})+unbind(load)"]
    return args


def render(found: Model, current: str) -> list[Group]:
    """Each group's header, open and shut, and its lines: the repos, then "other"."""
    named: list[tuple[str, Mapping[str, int], Sequence[Row]]] = [
        (str(repo.label) if repo.label else repo.name, repo.counts, repo.rows)
        for repo in found.repos
    ]
    if found.other:
        named.append(("other", Counter(row.state for row in found.other if row.state), found.other))
    every = [row for *_, members in named for row in members]
    width = min(WIDTH, max((len(_name(row)) for row in every), default=0))
    status_width = max((len(_status(row)) for row in every), default=0)
    groups: list[Group] = []
    for index, (title, counts, members) in enumerate(named):
        body = []
        for row in members:
            display = _worktree(row, current, width, status_width)
            body.append(_line(row.session.name, index, display))
            body += [
                _line(row.session.name, index, _agent(agent, n == len(row.agents) - 1))
                for n, agent in enumerate(row.agents)
            ]
        groups.append(
            {
                "open": _line("", index, _header("▾", title, counts)),
                "shut": _line("", index, _header("▸", title, counts)),
                "rows": body,
            }
        )
    return groups


def lines(groups: Sequence[Group], folded: Iterable[int] = ()) -> Iterator[str]:
    folded = set(folded)
    for index, group in enumerate(groups):
        shut = index in folded
        yield group["shut" if shut else "open"]
        if not shut:
            yield from group["rows"]


def cursor(groups: Sequence[Group], session: str) -> int | None:
    """The position of `session`'s worktree line, counting from 1."""
    found = (n for n, line in enumerate(lines(groups), 1) if line.partition("\t")[0] == session)
    return next(found, None) if session else None


def rows(folder: str) -> str:
    groups, folded = _load(folder)
    return "".join(f"{line}\n" for line in lines(groups, folded))


def fold(folder: str, group: str) -> str:
    """Toggles `group`'s fold, and gives the fzf actions that reload the lines with the cursor
    on its header. While searching, positions in fzf's list aren't ours to know."""
    groups, folded = _load(folder)
    index = int(group)
    folded ^= {index}
    Path(folder, FOLDED).write_text(json.dumps(sorted(folded)), encoding="utf-8")
    reload = f"reload:{shlex.join([*_self(), '__rows', folder])}"
    if os.environ.get("FZF_QUERY"):
        return reload
    above = groups[:index]
    header = 1 + sum(1 + (0 if i in folded else len(g["rows"])) for i, g in enumerate(above))
    return f"pos({header})+{reload}"


def _header(arrow: str, title: str, counts: Mapping[str, int]) -> str:
    shown = [(state, counts.get(state, 0)) for state in SUMMED]
    parts = [sgr(SGR[state], f"{n} {WORD[state]}") for state, n in shown if n]
    summary = "  " + sgr(DIM, " · ").join(parts) if parts else ""
    return f"{arrow} {sgr(BOLD, title)}{summary}"


def _worktree(row: Row, current: str, width: int, status_width: int) -> str:
    mark = sgr(CYAN, "▸") if row.session.name == current else " "
    state = row.state
    icon = sgr(SGR[state], ICON[state]) if state else ""
    status = _status(row)
    column = sgr(DIM, status) + " " * (status_width - len(status)) if status else " " * status_width
    gap = "  " if status_width else ""
    return f"{sgr(DIM, '│')} {mark} {_name(row).ljust(width)}{gap}{column}  {icon}".rstrip()


def _status(row: Row) -> str:
    found = row.status
    if not found:
        return ""
    parts = (f"~{found.changed}" if found.changed else "", f"↑{found.ahead}" if found.ahead else "")
    return " ".join(filter(None, parts))


def _agent(agent: Pane, last: bool) -> str:
    return sgr(DIM, f"│   {'└' if last else '├'} {describe(agent)}")


def describe(agent: Pane) -> str:
    who = "teammate" if agent.role == ps.TEAMMATE else agent.agent or ps.CLAUDE
    return f"{who} · win {agent.window} · {WORD[agent.state]}"


def _name(row: Row) -> str:
    return row.worktree.branch if row.worktree else row.session.name


def _line(session: str, group: int, display: str) -> str:
    return f"{session}\t{group}\t{display}"


def sgr(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _self() -> list[str]:
    return [sys.executable, "-m", "switchboard"]


def _load(folder: str) -> tuple[list[Group], set[int]]:
    groups = json.loads(Path(folder, MODEL).read_text(encoding="utf-8"))
    try:
        folded = set(json.loads(Path(folder, FOLDED).read_text(encoding="utf-8")))
    except OSError:
        folded = set()
    return groups, folded
