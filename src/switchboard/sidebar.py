"""The sidebar: the picker's list, compact and long-lived, in a pane of its own. Enter switches the
client viewing it, and the sidebar stays.

Its fzf listens on a local port, which it records with its API key in its pane's
`@switchboard-sidebar`. `refresh` finds them there, in the pane read it already makes, and asks
each sidebar to reload. `--toggle` finds a window's sidebar by the same option, which it sets to
`starting` on a pane it opens until fzf records its port. It keeps the window's layout from before
in `@switchboard-layout`, to put back when it closes the sidebar.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from switchboard import picker, run, theme, tmux

FOLDER = "SWITCHBOARD_SIDEBAR"
KEYS = "j:down,k:up,q:ignore"
HOST = "127.0.0.1"
TIMEOUT = 0.2
COLUMNS = 32
STARTING = "starting"
LAYOUT = "@switchboard-layout"


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
        groups = _draw(folder, current)
        result = subprocess.run(
            ["fzf", *fzf_args(folder, picker.cursor(groups, current))],
            input=picker.rows(folder),
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


def fzf_args(folder: str, at: int | None) -> list[str]:
    """The picker's keys without its hints, and nothing closes it: `q` does nothing, and so does
    Esc outside a search. Enter and a double click switch, through a binding that never accepts."""
    switch = shlex.join([*picker.command(), "__switch"])
    listen = shlex.join([*picker.command(), "__listen"])
    return [
        *picker.list_args(folder, at, KEYS, ("", ""), "ignore"),
        f"--listen={HOST}:0",
        "--bind",
        f"start:execute-silent:{listen}",
        "--bind",
        f"enter,double-click:transform:{switch} {{1}}",
    ]


def listen() -> None:
    """fzf's start: its port and API key go on the sidebar's pane, where `refresh` finds them."""
    pane, port, key = (
        os.environ.get(name, "") for name in ("TMUX_PANE", "FZF_PORT", "FZF_API_KEY")
    )
    if pane and port:
        run.tmux(("set-option", "-p", "-t", pane, tmux.SIDEBAR, f"{port} {key}"))


def switch(session: str) -> str:
    """Switches the client viewing the sidebar, which tmux finds from `$TMUX_PANE`, and gives the
    actions that leave any search."""
    if not session:
        return ""
    run.tmux(("switch-client", "-t", f"={session}"))
    return picker.back("")


def redraw(folder: str) -> str:
    """The lines a poke reloads, built again from tmux."""
    if not folder:
        return ""
    from switchboard import attention

    _draw(folder, attention.current_session() or "")
    return picker.rows(folder)


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


def _draw(folder: str, current: str) -> list[picker.Group]:
    """Renders the compact list into `folder`, keeping the repos folded there folded."""
    from switchboard import model

    os.environ[theme.ENV] = theme.detect()
    groups = picker.render(model.load(), current, compact=True)
    try:
        before, folded = picker.cached(folder)
    except OSError:
        before, folded = [], set()
    shut = {before[index]["title"] for index in folded if index < len(before)}
    folded = {index for index, group in enumerate(groups) if group["title"] in shut}
    Path(folder, picker.MODEL).write_text(json.dumps(groups), encoding="utf-8")
    Path(folder, picker.FOLDED).write_text(json.dumps(sorted(folded)), encoding="utf-8")
    return groups
