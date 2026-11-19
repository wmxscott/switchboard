"""The alert: a tmux message on each client, and one short sound in the background."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Iterable

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


def send(state: str, session: str, clients: Iterable[str]) -> None:
    text = TEXT[state].format(session).replace("#", "##")
    commands = [("display-message", "-c", client, "-d", DELAY, text) for client in clients]
    if commands:
        run.tmux(*commands)
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
