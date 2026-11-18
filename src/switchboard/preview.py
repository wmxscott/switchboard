"""The picker's preview of a session: its name and folder, its windows, and the last lines of its
most urgent agent's pane, else of its active pane. Two tmux calls; one that fails leaves out what
it would have shown."""

from __future__ import annotations

import os
from dataclasses import dataclass

from switchboard import panestate as ps
from switchboard import run
from switchboard.picker import BOLD, CYAN, DIM, ICON, SGR, describe, sgr
from switchboard.tmux import Pane

HEIGHT = 40
FIELDS = (
    "session_path",
    "window_index",
    "window_active",
    "pane_id",
    "pane_active",
    "pane_current_command",
    *ps.OPTIONS,
    "window_name",
)


@dataclass(frozen=True)
class Window:
    index: int
    name: str
    active: bool


@dataclass(frozen=True)
class Layout:
    path: str
    windows: tuple[Window, ...]
    panes: tuple[Pane, ...]
    active: Pane


def show(session: str, height: int = HEIGHT) -> str:
    """At most `height` lines, and nothing for a repo header's empty session."""
    if not session:
        return ""
    lines = [sgr(BOLD, session)]
    found = layout(session)
    if found:
        lines += [sgr(DIM, _home(found.path)), "", sgr(DIM, "windows")]
        lines += [_window(window, found.panes) for window in found.windows]
        agents = [pane for pane in found.panes if pane.is_agent]
        pane = min(agents, key=lambda a: ps.URGENCY.index(a.state)) if agents else found.active
        last = _last(pane.id, height - len(lines) - 2)
        if last is not None:
            lines += ["", sgr(DIM, describe(pane) if pane.is_agent else _plain(pane)), *last]
    return "".join(f"{line}\n" for line in lines)


def layout(session: str) -> Layout | None:
    fmt = "\t".join(f"#{{{field}}}" for field in FIELDS)
    out = run.output("tmux", "list-panes", "-s", "-t", f"={session}", "-F", fmt)
    path, windows, panes, active = "", {}, [], None
    for line in (out or "").splitlines():
        fields = line.split("\t", len(FIELDS) - 1)
        if len(fields) != len(FIELDS) or not fields[1].isdecimal():
            continue
        path, index, window_on, pane_id, pane_on, command, *options, name = fields
        role, turn, pending, _, agent = options
        keys = ps.decode_pending(pending)
        pane = Pane(session, int(index), pane_id, command, role, turn, keys, agent=agent)
        windows.setdefault(pane.window, Window(pane.window, name, window_on == "1"))
        panes.append(pane)
        if window_on == pane_on == "1":
            active = pane
    if active is None:
        return None
    return Layout(path, tuple(windows.values()), tuple(panes), active)


def _window(window: Window, panes: tuple[Pane, ...]) -> str:
    mark = sgr(CYAN, "▸") if window.active else " "
    state = ps.most_urgent(p.state for p in panes if p.window == window.index and p.is_agent)
    icon = f" {sgr(SGR[state], ICON[state])}" if state else ""
    return f"{mark} {window.index} {window.name}{icon}"


def _last(pane: str, room: int) -> list[str] | None:
    """The pane's last `room` lines that aren't trailing blanks, reaching into its history when
    the screen's own lines run out."""
    if room < 1:
        return None
    out = run.output("tmux", "capture-pane", "-p", "-J", "-t", pane, "-S", f"-{room}")
    if out is None:
        return None
    lines = [line.rstrip() for line in out.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines[-room:]


def _plain(pane: Pane) -> str:
    return f"{pane.command} · win {pane.window}"


def _home(path: str) -> str:
    home = os.path.expanduser("~").rstrip("/")
    if home and (path == home or path.startswith(f"{home}/")):
        return f"~{path[len(home) :]}"
    return path
