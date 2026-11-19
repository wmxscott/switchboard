"""The picker: tmux sessions in fzf, grouped by repo with their agents, switching the client that
opened it.

Each fzf line is `session<TAB>pane<TAB>group<TAB>display`, with only the display shown. The pane is
where picking the line lands: an agent row's own, a worktree row's most urgent agent's, or none. A
repo header has no session. Folding reloads the lines from a cache in a temporary folder, so it
never re-runs git.
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
from switchboard import run, theme

if TYPE_CHECKING:
    from switchboard.model import Model, Row
    from switchboard.tmux import Pane

MIN_FZF = (0, 59)
KEYS = "j:down,k:up,q:abort"
# fzf drops any change to the query made while its input is hidden, which Esc's transform ends with,
# so `/` clears the query once the input shows, and Esc only searches for nothing.
SEARCH_KEYS = "show-input+clear-query+unbind(j,k,/,q)"
BACK_KEYS = "search()+hide-input+rebind(j,k,/,q)"
HINT = "j/k move · / search · tab fold · ↵ switch · q/esc close"
SEARCH_HINT = "↑/↓ move · tab fold · ↵ switch · esc back"
LOOK = ("--layout=reverse", "--height=100%", "--border=none", "--margin=0", "--padding=0")
PREVIEW = "right,60%,border-left,noinfo"

DOT, DOT_FILL = "\ueabc", "\uf111"  # nf-cod-circle, nf-fa-circle
OPEN, SHUT = "\uf0d7", "\uf0da"  # nf-fa-caret_down, nf-fa-caret_right
HERE = "\uf192"  # nf-fa-circle_dot
ICON = {ps.NEEDS: DOT_FILL, ps.DONE: DOT_FILL, ps.WORKING: DOT_FILL, ps.IDLE: DOT}
WORD = {ps.NEEDS: "needs you", ps.DONE: "done", ps.WORKING: "working", ps.IDLE: "idle"}
SGR = {ps.NEEDS: "red", ps.DONE: "green", ps.WORKING: "peach", ps.IDLE: "green"}
SUMMED = (ps.NEEDS, ps.DONE, ps.WORKING)
TEXT, BOLD, DIM, LINE = "text", "bold text", "subtext0", "overlay1"
MUTED, CURRENT = "dim overlay0", "bold green"
WIDTH, NARROW = 40, 20
NARROW_TITLE = NARROW + 3  # a shut header with its dot as wide as a worktree row

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

    # The preview, which fzf runs, inherits it.
    os.environ[theme.ENV] = theme.detect()
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
    session, pane = [*result.stdout.split("\t"), "", ""][:2]
    if session and not switch(session, pane, client):
        raise PickerError(f"can't switch to {session}")
    return 0


def switch(session: str, pane: str, client: str = "") -> bool:
    """Switches the client to `pane`, else to `session`: the pane may have closed since the list
    was drawn."""
    flags = ("-c", client) if client else ()
    targets = (pane, f"={session}") if pane else (f"={session}",)
    return any(run.tmux(("switch-client", *flags, "-t", target)) is not None for target in targets)


def fzf_problem(who: str = "the picker") -> str | None:
    words = (run.output("fzf", "--version") or "").split()
    found = words[0] if words else "none"
    parts = found.split(".")
    numbers = [int(part) for part in parts[:2] if part.isdecimal()]
    if len(numbers) == 2 and tuple(numbers) >= MIN_FZF:
        return None
    return f"{who} needs fzf {'.'.join(map(str, MIN_FZF))} or newer; found {found}"


def pinned() -> tuple[str, str]:
    """The client and its session, read once: later, tmux's idea of the current client can move."""
    out = run.output("tmux", "display-message", "-p", "#{client_name}\t#{session_name}")
    client, _, session = (out or "").removesuffix("\n").partition("\t")
    return client, session


def fzf_args(folder: str, at: int | None) -> list[str]:
    preview = shlex.join([*command(), "__preview"])
    return [
        *list_args(folder, at, KEYS, (HINT, SEARCH_HINT), "abort"),
        f"--preview={preview} {{1}} {{2}}",
        f"--preview-window={PREVIEW}",
        "--bind",
        "enter:transform:[ -n {1} ] && echo accept",
    ]


def list_args(
    folder: str, at: int | None, keys: str, hints: tuple[str, str], leave: str
) -> list[str]:
    """Search starts off: `/` shows an empty input line, and Esc then hides it and shows every line
    again. Out of a search, Esc does `leave`."""
    hint, search_hint = hints
    fold = shlex.join([*command(), "__fold", folder])
    out = shlex.quote(back(hint))
    args = [
        "--ansi",
        "--no-sort",
        *LOOK,
        "--no-info",
        "--prompt=> ",
        "--no-input",
        "--bind",
        keys,
        "--bind",
        f"/:{SEARCH_KEYS}{_change_header(search_hint)}",
        "--bind",
        f'esc:transform:[ "$FZF_INPUT_STATE" = enabled ] && printf %s {out} || echo {leave}',
        "--delimiter=\t",
        "--with-nth=4",
        "--with-shell=sh -c",
        *([f"--header={_hints(hint)}"] if hint else []),
        "--bind",
        f"tab:transform:{fold} {{3}}",
    ]
    if at:
        args += ["--bind", f"load:pos({at})+unbind(load)"]
    return args


def back(hint: str) -> str:
    """The actions that leave a search."""
    return f"{BACK_KEYS}{_change_header(hint)}"


def render(found: Model, current: str, compact: bool = False) -> list[Group]:
    """Each group's title, its header open and shut, and its lines: the repos, then "other". The
    compact list has no agent lines, counts or git status, and cuts long names short. Its shut
    header shows the group's most urgent dot instead, so that a fold never hides one."""
    named: list[tuple[str, Mapping[str, int], Sequence[Row]]] = [
        (str(repo.label) if repo.label else repo.name, repo.counts, repo.rows)
        for repo in found.repos
    ]
    if found.other:
        named.append(("other", Counter(row.state for row in found.other if row.state), found.other))
    every = [row for *_, members in named for row in members]
    width = min(NARROW if compact else WIDTH, max((len(_name(row)) for row in every), default=0))
    status_width = 0 if compact else max((len(_status(row)) for row in every), default=0)
    groups: list[Group] = []
    for index, (title, counts, members) in enumerate(named):
        body = []
        for row in members:
            display = _worktree(row, current, width, status_width, compact)
            target = row.target
            body.append(_line(row.session.name, target.id if target else "", index, display))
            body += [
                _line(row.session.name, agent.id, index, _agent(agent, n == len(row.agents) - 1))
                for n, agent in enumerate(() if compact else row.agents)
            ]
        shown = {} if compact else counts
        name = _cut(title, NARROW_TITLE) if compact else title
        state = ps.most_urgent(counts) if compact else None
        dot = f" {sgr(SGR[state], ICON[state])}" if state else ""
        groups.append(
            {
                "title": title,
                "open": _line("", "", index, _header(OPEN, name, shown)),
                "shut": _line("", "", index, _header(SHUT, name, shown) + dot),
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
    groups, folded = cached(folder)
    return "".join(f"{line}\n" for line in lines(groups, folded))


def fold(folder: str, group: str) -> str:
    """Toggles `group`'s fold, and gives the fzf actions that reload the lines with the cursor
    on its header. While searching, positions in fzf's list aren't ours to know. Out of a search,
    fzf still reports the last search's query, though it no longer filters."""
    groups, folded = cached(folder)
    index = int(group)
    folded ^= {index}
    Path(folder, FOLDED).write_text(json.dumps(sorted(folded)), encoding="utf-8")
    reload = f"reload:{shlex.join([*command(), '__rows', folder])}"
    if os.environ.get("FZF_INPUT_STATE") == "enabled" and os.environ.get("FZF_QUERY"):
        return reload
    above = groups[:index]
    header = 1 + sum(1 + (0 if i in folded else len(g["rows"])) for i, g in enumerate(above))
    return f"pos({header})+{reload}"


def _change_header(hint: str) -> str:
    return f"+change-header:{_hints(hint)}" if hint else ""


def _hints(text: str) -> str:
    """fzf's header: the hints between blank rows."""
    return " \n" + "\n".join(sgr(MUTED, line) for line in text.split("\n")) + "\n "


def _header(caret: str, title: str, counts: Mapping[str, int]) -> str:
    shown = [(state, counts.get(state, 0)) for state in SUMMED]
    parts = [sgr(SGR[state], f"{n} {WORD[state]}") for state, n in shown if n]
    summary = "  " + sgr(LINE, " · ").join(parts) if parts else ""
    return f"{sgr(TEXT, caret)} {sgr(BOLD, title)}{summary}"


def _worktree(row: Row, current: str, width: int, status_width: int, cut: bool = False) -> str:
    mark = sgr(CURRENT, HERE) if row.session.name == current else " "
    state = row.state
    icon = sgr(SGR[state], ICON[state]) if state else ""
    status = _status(row) if status_width else ""
    column = sgr(DIM, status) + " " * (status_width - len(status)) if status else " " * status_width
    gap = "  " if status_width else ""
    text = _cut(_name(row), width) if cut else _name(row)
    name = sgr(TEXT, text) + " " * (width - len(text))
    return f"{sgr(LINE, '│')} {mark} {name}{gap}{column}  {icon}".rstrip()


def _status(row: Row) -> str:
    found = row.status
    if not found:
        return ""
    parts = (f"~{found.changed}" if found.changed else "", f"↑{found.ahead}" if found.ahead else "")
    return " ".join(filter(None, parts))


def _agent(agent: Pane, last: bool) -> str:
    tree = sgr(LINE, f"│   {'└' if last else '├'}")
    return f"{tree} {sgr(SGR[agent.state], ICON[agent.state])} {sgr(DIM, describe(agent))}"


def describe(agent: Pane) -> str:
    who = "teammate" if agent.role == ps.TEAMMATE else agent.agent or ps.CLAUDE
    return f"{who} · win {agent.window} · {WORD[agent.state]}"


def _cut(text: str, width: int) -> str:
    return text[: width - 1] + "…" if len(text) > width else text


def _name(row: Row) -> str:
    return row.worktree.branch if row.worktree else row.session.name


def _line(session: str, pane: str, group: int, display: str) -> str:
    return f"{session}\t{pane}\t{group}\t{display}"


def sgr(style: str, text: str) -> str:
    return f"\033[{theme.sgr(style)}m{text}\033[0m"


def command() -> list[str]:
    """switchboard itself, for fzf's bindings to call back into."""
    return [sys.executable, "-m", "switchboard"]


def cached(folder: str) -> tuple[list[Group], set[int]]:
    groups = json.loads(Path(folder, MODEL).read_text(encoding="utf-8"))
    try:
        folded = set(json.loads(Path(folder, FOLDED).read_text(encoding="utf-8")))
    except OSError:
        folded = set()
    return groups, folded
