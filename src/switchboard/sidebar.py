"""The sidebar: the picker's list, compact and long-lived, in a pane of its own, with a card under
it for each agent elsewhere that needs the user or is done. Enter switches the client viewing it,
and the sidebar stays. Its items end with a NUL (`--read0`), so that a card can span two lines.

Its fzf listens on a local port, which it records with its API key in its pane's
`@switchboard-sidebar`. `refresh` finds them there, in the pane read it already makes, and asks
each sidebar to reload. `--toggle` finds a window's sidebar by the same option, which it sets to
`starting` on a pane it opens until fzf records its port. It keeps the window's layout from before
in `@switchboard-layout`, to put back when it closes the sidebar.

Each list it gives fzf, it also writes to its folder by who each item is, with where in it the
cursor goes from each row of the list fzf shows. fzf's load binding moves the cursor there, so that
a redraw never moves it off its item.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from switchboard import cards, picker, run, theme, tmux

FOLDER = "SWITCHBOARD_SIDEBAR"
STEP = f"[ {{3}} = {cards.GAP} ] && echo"
KEYS = f"j,down:down+transform({STEP} down),k,up:up+transform({STEP} up),g:first,G:last,q:ignore"
HELD = "j,k,g,G,/,q"
HOST = "127.0.0.1"
TIMEOUT = 0.2
COLUMNS = 32
STARTING = "starting"
LAYOUT = "@switchboard-layout"
CARDS = "cards.json"
SHOWN, NEXT, MOVES = "shown.json", "next.json", "moves"
# Once a list lands, it's the one fzf shows, and the cursor, which fzf left on its row, goes to that
# row's item in it. A search's rows aren't ours to know.
LAND = (
    f'd=${FOLDER}; mv "$d/{NEXT}" "$d/{SHOWN}" 2>/dev/null && '
    '{ [ "$FZF_INPUT_STATE" = enabled ] && [ -n "$FZF_QUERY" ] || '
    f"""awk -v n="$FZF_POS" 'NR == n' "$d/{MOVES}"; }}"""
)
HEAD, ROW, CARD, MORE = "head", "row", "card", "more"
LISTED = (HEAD, ROW)
EDGE = 3  # fzf's pointer and marker columns, and the one it keeps for a scrollbar


def show() -> int:
    pane = os.environ.get("TMUX_PANE")
    if not pane or not os.environ.get("TMUX"):
        raise picker.PickerError("the sidebar only runs inside tmux")
    problem = picker.fzf_problem("the sidebar")
    if problem:
        raise picker.PickerError(problem)
    from switchboard import attention

    folder = tempfile.mkdtemp(prefix="switchboard-")
    # Taken before _draw() fixes this process's theme, so that each reload finds it again.
    env = {**os.environ, "FZF_API_KEY": os.urandom(16).hex(), FOLDER: folder}
    try:
        current = attention.current_session() or ""
        _draw(folder, current)
        # As though fzf showed only the current session's row, so that the first list keeps the
        # cursor on it.
        Path(folder, SHOWN).write_text(json.dumps([(ROW, current)]), encoding="utf-8")
        result = subprocess.run(
            ["fzf", *fzf_args(folder)],
            input=rows(folder),
            stdout=subprocess.PIPE,
            env=env,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        run.tmux(("set-option", "-p", "-u", "-t", pane, tmux.SIDEBAR))
        shutil.rmtree(folder, ignore_errors=True)
    if result.returncode not in (0, 1, 130):
        raise picker.PickerError(f"fzf exited with status {result.returncode}")
    return result.returncode


def toggle(pane: str) -> None:
    """Closes the sidebar in `pane`'s window, or opens one down the window's left edge, without
    moving the focus."""
    pane = pane or os.environ.get("TMUX_PANE", "")
    if not pane or not os.environ.get("TMUX"):
        raise picker.PickerError("the sidebar only runs inside tmux")
    fields = f"#{{pane_id}}\t#{{{tmux.SIDEBAR}}}\t#{{{LAYOUT}}}\t#{{window_layout}}"
    found = run.output("tmux", "list-panes", "-F", fields, "-t", pane)
    if found is None:
        raise picker.PickerError(f"can't find pane {pane}")
    panes = [(line.split("\t", 3) + [""] * 3)[:4] for line in found.splitlines()]
    sidebars = [(pane_id, saved) for pane_id, tag, saved, _ in panes if tag]
    if sidebars:
        others = [pane_id for pane_id, tag, _, _ in panes if not tag]
        kill = [("kill-pane", "-t", pane_id) for pane_id, _ in sidebars]
        after = [("display-message", "-p", "-t", others[0], "#{window_layout}")] if others else []
        now = run.tmux(*kill, *after)
        if now is None:
            raise picker.PickerError("can't close the sidebar")
        layout = _restored(sidebars[0][1], now)
        if layout:
            run.tmux(("select-layout", "-t", others[0], layout))
        return
    # tmux-resurrect saves the command a pane's shell runs, so the sidebar runs under one. `; exit`
    # keeps `sh` from exec'ing it.
    launch = ("sh", "-c", f"{shlex.join([*picker.command(), 'sidebar'])}; exit")
    split = ("split-window", "-hbdf", "-l", str(COLUMNS), "-P", "-F", "#{pane_id}", "-t", pane)
    opened = (run.output("tmux", *split, *launch) or "").strip()
    if not opened:
        raise picker.PickerError("can't open the sidebar")
    # `-o`: fzf may already have recorded its port.
    run.tmux(
        ("set-option", "-p", "-t", opened, LAYOUT, panes[0][3]),
        ("set-option", "-p", "-o", "-q", "-t", opened, tmux.SIDEBAR, STARTING),
    )


def _restored(saved: str, now: str) -> str | None:
    """The window's layout from before the sidebar opened, which gives back the widths it took,
    with the focus and last-pane history tmux left `now` it has closed. tmux refuses it if the panes
    have changed."""
    try:
        layout, marks = json.loads(saved), {p["I"]: p for p in _panes(json.loads(now)["L"])}
        for cell in _panes(layout["L"]):
            for key in ("a", "l"):
                cell.pop(key, None)
                if key in marks.get(cell["I"], {}):
                    cell[key] = marks[cell["I"]][key]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return json.dumps(layout, separators=(",", ":"))


def _panes(cell: dict) -> Iterable[dict]:
    if cell.get("t") == "p":
        yield cell
    for child in cell.get("c", ()):
        yield from _panes(child)


def fzf_args(folder: str) -> list[str]:
    """The picker's keys without its hints, and nothing closes it: `q` does nothing, and so does
    Esc outside a search. Enter and a double click switch, through a binding that never accepts.
    `j` and `k` step over the gap above any cards, `g` and `G` go to either end, and a resize fits
    the gap again."""
    switch = shlex.join([*picker.command(), "__switch"])
    listen = shlex.join([*picker.command(), "__listen"])
    again = shlex.join([*picker.command(), "__rows0", folder])
    return [
        *picker.list_args(folder, None, KEYS, ("", ""), "ignore", read0=True, held=HELD),
        f"--listen={HOST}:0",
        "--bind",
        f"start:execute-silent:{listen}",
        "--bind",
        f"load:transform:{LAND}",
        "--bind",
        f"resize:reload:{again}",
        "--bind",
        f"enter,double-click:transform:{switch} {{1}} {{2}}",
    ]


def listen() -> None:
    """fzf's start: its port and API key go on the sidebar's pane, where `refresh` finds them."""
    pane, port, key = (
        os.environ.get(name, "") for name in ("TMUX_PANE", "FZF_PORT", "FZF_API_KEY")
    )
    if pane and port:
        run.tmux(("set-option", "-p", "-t", pane, tmux.SIDEBAR, f"{port} {key}"))


def switch(session: str, pane: str) -> str:
    """Switches the client viewing the sidebar, which tmux finds from `$TMUX_PANE`, and gives the
    actions that leave any search."""
    if not session:
        return ""
    picker.switch(session, pane)
    return picker.back("", HELD)


def redraw(folder: str) -> str:
    """The items a poke reloads, built again from tmux."""
    if not folder:
        return ""
    from switchboard import attention

    _draw(folder, attention.current_session() or "")
    return rows(folder)


def rows(folder: str) -> str:
    """The list cached in `folder`, then any cards, fitted to fzf's rows and columns."""
    groups, folded = picker.cached(folder)
    listed = list(picker.lines(groups, folded))
    height, columns = _size()
    stack = cards.stack(_cards(folder), height - len(listed), columns - EDGE)
    shown = [*listed, *stack]
    _aim(folder, [_key(item, groups) for item in shown])
    return "".join(f"{item}\0" for item in shown)


Key = tuple[str, ...]


def _key(item: str, groups: Sequence[picker.Group]) -> Key:
    """Who an item is across redraws: a row's session, a header's repo, or a card's agent."""
    session, pane, group = item.split("\t", 3)[:3]
    if group.isdecimal():
        return (ROW, session) if session else (HEAD, groups[int(group)]["title"])
    if group == cards.GAP:
        return (cards.GAP,)
    return (CARD, pane) if session else (MORE,)


def _aim(folder: str, new: list[Key]) -> None:
    """Leaves `new` for the load binding, with where in it each row's item of the list fzf shows
    goes."""
    try:
        old = [tuple(key) for key in json.loads(Path(folder, SHOWN).read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        old = []
    moves = [f"pos({n + 1})" for n in steady(old, new)]
    at = _cursor()
    if 0 < len(new) < at <= len(old):
        # fzf cuts the cursor's row to the new list's last.
        moves[len(new) - 1] = moves[at - 1]
    Path(folder, NEXT).write_text(json.dumps(new), encoding="utf-8")
    Path(folder, MOVES).write_text("".join(f"{move}\n" for move in moves), encoding="utf-8")


def steady(old: Sequence[Key], new: Sequence[Key]) -> list[int]:
    """Where in `new` each of `old`'s items goes, by index: to itself, else to the nearest of its
    kind that's left, after it then before it. A row's or a header's kind is the list, failing
    which it goes to the first row. A card's kind is the cards, failing which it goes to the newest
    card, or the list's last row. `+N more` and the gap go to the first card, or the list's last
    row."""
    where: dict[Key, int] = {}
    for n, key in enumerate(new):
        where.setdefault(key, n)
    listed = [n for n, key in enumerate(new) if key[0] in LISTED] or [0]
    stacked = [n for n, key in enumerate(new) if key[0] == CARD] or listed[-1:]
    moves = []
    for i, key in enumerate(old):
        if key in where:
            moves.append(where[key])
            continue
        if key[0] in LISTED:
            kinds, last = LISTED, listed[0]
        elif key[0] == CARD:
            kinds, last = (CARD,), stacked[-1]
        else:
            kinds, last = (), stacked[0]
        around = (*old[i + 1 :], *reversed(old[:i]))
        moves.append(next((where[k] for k in around if k[0] in kinds and k in where), last))
    return moves


def _cursor() -> int:
    """The cursor's row in the list fzf shows, from 1, or 0 while a search filters it."""
    if os.environ.get("FZF_INPUT_STATE") == "enabled" and os.environ.get("FZF_QUERY"):
        return 0
    found = os.environ.get("FZF_POS", "")
    return int(found) if found.isdecimal() else 0


def _size() -> tuple[int, int]:
    """fzf's rows and columns: its own in a reload, else the terminal's that it's about to fill."""
    lines, columns = (os.environ.get(name, "") for name in ("FZF_LINES", "FZF_COLUMNS"))
    if lines.isdecimal() and columns.isdecimal():
        return int(lines), int(columns)
    size = shutil.get_terminal_size((COLUMNS, 0))
    return size.lines, size.columns


def _cards(folder: str) -> list[cards.Card]:
    """The cards cached in `folder`, drawn in the theme the list was."""
    try:
        saved = json.loads(Path(folder, CARDS).read_text(encoding="utf-8"))
    except OSError:
        return []
    os.environ[theme.ENV] = saved["theme"]
    return [cards.Card(**card) for card in saved["cards"]]


def poke(endpoints: Iterable[str]) -> None:
    """Asks each sidebar's fzf to reload, without waiting for its answer. A dead one refuses the
    connection at once."""
    body = f"reload:{shlex.join([*picker.command(), '__redraw'])}".encode()
    for endpoint in endpoints:
        port, _, key = endpoint.partition(" ")
        head = f"POST / HTTP/1.1\r\nx-api-key: {key}\r\ncontent-length: {len(body)}\r\n\r\n"
        with (
            contextlib.suppress(OSError, ValueError, OverflowError),
            socket.create_connection((HOST, int(port)), timeout=TIMEOUT) as conn,
        ):
            conn.sendall(head.encode() + body)


def _draw(folder: str, current: str) -> None:
    """Renders the compact list into `folder`, keeping the repos folded there folded, with the
    cards for every session but `current`."""
    from switchboard import model

    os.environ[theme.ENV] = theme.detect()
    found = model.load()
    groups = picker.render(found, current, compact=True)
    try:
        before, folded = picker.cached(folder)
    except OSError:
        before, folded = [], set()
    shut = {before[index]["title"] for index in folded if index < len(before)}
    folded = {index for index, group in enumerate(groups) if group["title"] in shut}
    Path(folder, picker.MODEL).write_text(json.dumps(groups), encoding="utf-8")
    Path(folder, picker.FOLDED).write_text(json.dumps(sorted(folded)), encoding="utf-8")
    every = [*(row for repo in found.repos for row in repo.rows), *found.other]
    shown = cards.build((agent for row in every for agent in row.agents), current)
    saved = {"theme": os.environ[theme.ENV], "cards": [dataclasses.asdict(c) for c in shown]}
    Path(folder, CARDS).write_text(json.dumps(saved), encoding="utf-8")
