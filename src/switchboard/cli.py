"""Command-line interface."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # The hook runs on every Claude tool call: skip argparse.
    if argv[:1] == ["hook"]:
        return hook()
    return _main(argv)


def _main(argv: list[str]) -> int:
    import argparse

    from switchboard import __version__

    parser = argparse.ArgumentParser(
        prog="switchboard",
        description="Switch between tmux sessions, and see which Claude Code agents need you."
        " With no command, open the picker.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("hook", help="Claude Code hook entry point, reading the hook JSON on stdin")
    p.add_argument("event", nargs="?", help="the hook event, such as Stop")
    p.set_defaults(func=lambda args: hook())

    p = sub.add_parser("seen", help="mark the current session's finished agents seen")
    p.set_defaults(func=cmd_seen)

    p = sub.add_parser("refresh", help="rebuild the status bar's attention list")
    p.set_defaults(func=cmd_refresh)

    args = parser.parse_args(argv)
    if not args.command:
        return cmd_pick(args)
    return args.func(args)


def _err(message: str) -> None:
    print(f"switchboard: {message}", file=sys.stderr)


def hook() -> int:
    import contextlib

    with contextlib.suppress(Exception):
        # Never block on a terminal.
        if sys.stdin is not None and not sys.stdin.isatty():
            sys.stdin.buffer.read()
    return 0


def cmd_pick(args) -> int:
    _err("the picker isn't built yet")
    return 1


def cmd_seen(args) -> int:
    return 0


def cmd_refresh(args) -> int:
    return 0
