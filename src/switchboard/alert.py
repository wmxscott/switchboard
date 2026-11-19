"""The alert: a tmux message on each client whose window has no sidebar, and one short sound in
the background."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Container, Iterable

from switchboard import panestate as ps
from switchboard import run

SOUNDS = (
    "/System/Library/Sounds/Glass.aiff",
    "/System/Library/Sounds/Tink.aiff",
    "/System/Library/Sounds/Ping.aiff",
)
DELAY = "4000"
TEXT = {ps.NEEDS: "▲ {} needs you", ps.DONE: "✓ {} is done"}

State = tuple[str, ...]


def news(before: State, after: State) -> str | None:
    """The displayed state a change between two (role, turn, pending, ...) states alerts about.

    Needs-you for any agent; done only for a lead, since teammates go idle between messages.
    """
    shown = _shown(after)
    if shown == _shown(before) or (shown == ps.DONE and after[0] != ps.LEAD):
        return None
    return shown if shown in (ps.NEEDS, ps.DONE) else None


def send(state: str, session: str, clients: Iterable[str], sidebars: Container[str] = ()) -> None:
    """Messages each client but those in `sidebars`, whose sidebar shows the agent's card instead,
    and plays the sound when there's any client."""
    clients = list(clients)
    text = TEXT[state].format(session).replace("#", "##")
    run.tmux(
        *(("display-message", "-c", c, "-d", DELAY, text) for c in clients if c not in sidebars)
    )
    if clients:
        play()


def sound() -> str | None:
    """`$SWITCHBOARD_SOUND`, where empty means none, else the first system sound that exists."""
    chosen = os.environ.get("SWITCHBOARD_SOUND")
    if chosen is not None:
        return chosen or None
    return next((path for path in SOUNDS if os.path.isfile(path)), None)


def play() -> subprocess.Popen | None:
    """Starts the sound detached, without waiting for it."""
    path = sound()
    player = shutil.which("afplay")
    if not path or not player:
        return None
    with contextlib.suppress(OSError):
        return subprocess.Popen(
            [player, path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return None


def _shown(state: State) -> str:
    _, turn, pending, *_ = state
    return ps.display(turn, ps.decode_pending(pending))
