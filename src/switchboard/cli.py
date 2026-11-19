"""Command-line interface."""

from __future__ import annotations

import sys
from collections.abc import Sequence

STATE_USAGE = (
    "<start|working [--task TEXT]|done|idle|needs KEY [--reason TEXT]|resolve KEY|all|end>"
    " [--agent NAME]"
)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Hooks run on every agent tool call: skip argparse.
    if argv[:1] == ["hook"]:
        return cmd_hook(argv[1:])
    if argv[:1] == ["state"]:
        return cmd_state(argv[1:])
    if argv[:1] in (["__rows"], ["__fold"]):
        return cmd_picker_reload(argv)
    if argv[:1] == ["__preview"]:
        return cmd_preview(argv[1:])
    if argv[:1] in (["__listen"], ["__redraw"], ["__switch"]):
        return cmd_sidebar_binding(argv)
    return _main(argv)


def _main(argv: list[str]) -> int:
    import argparse

    from switchboard import __version__

    parser = argparse.ArgumentParser(
        prog="switchboard",
        description="Switch between tmux sessions, and see which coding agents need you."
        " With no command, open the picker.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("hook", help="an agent's hook entry point, reading the hook JSON on stdin")
    p.add_argument("--agent", default="claude", help="the agent, by default claude")
    p.add_argument("event", nargs="?", help="the hook event, such as Stop")
    p.set_defaults(func=lambda args: cmd_hook(["--agent", args.agent, *filter(None, [args.event])]))

    sub.add_parser("state", help="set this pane's agent state, for an agent with no adapter")

    p = sub.add_parser("seen", help="mark a session's finished agents seen")
    p.add_argument("session", nargs="?", help="the session, by default the current one")
    p.set_defaults(func=cmd_seen)

    p = sub.add_parser("refresh", help="rebuild the status bar's attention list")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("sidebar", help="the picker's list, compact and live, in this pane")
    p.add_argument(
        "--toggle",
        nargs="?",
        const="",
        metavar="PANE",
        help="close the sidebar in PANE's window, or open one there; by default, this pane's",
    )
    p.set_defaults(func=cmd_sidebar)

    args = parser.parse_args(argv)
    if not args.command:
        return cmd_pick(args)
    return args.func(args)


def _err(message: str) -> None:
    print(f"switchboard: {message}", file=sys.stderr)


def cmd_hook(args: list[str]) -> int:
    """Silent and always 0: a failing hook must never get in Claude's way."""
    import os

    pane = os.environ.get("TMUX_PANE")
    if not pane or sys.stdin is None:
        return 0
    import contextlib

    with contextlib.suppress(Exception):
        if not sys.stdin.isatty():
            from switchboard import hook

            hook.handle(args, pane, sys.stdin.buffer.read())
    return 0


def cmd_state(args: list[str]) -> int:
    """Silent and always 0 at runtime, like the hook; malformed arguments exit 2."""
    import os

    from switchboard import core

    found = core.split_agent(args)
    verb = core.parse(found[1]) if found else None
    if found is None or verb is None:
        print(f"usage: switchboard state {STATE_USAGE}", file=sys.stderr)
        return 2
    pane = os.environ.get("TMUX_PANE")
    if pane:
        import contextlib

        with contextlib.suppress(Exception):
            core.perform(pane, [verb], found[0])
    return 0


def cmd_pick(args) -> int:
    from switchboard import picker

    try:
        return picker.pick()
    except picker.PickerError as error:
        _err(str(error))
        return 1


def cmd_picker_reload(argv: list[str]) -> int:
    """The picker's own fzf bindings: `__rows <folder>` and `__fold <folder> <group>`."""
    from switchboard import picker

    if argv[0] == "__rows":
        sys.stdout.write(picker.rows(argv[1]))
    else:
        print(picker.fold(argv[1], argv[2]))
    return 0


def cmd_sidebar(args) -> int:
    from switchboard import picker, sidebar

    try:
        if args.toggle is None:
            return sidebar.show()
        sidebar.toggle(args.toggle)
        return 0
    except picker.PickerError as error:
        _err(str(error))
        return 1


def cmd_sidebar_binding(argv: list[str]) -> int:
    """The sidebar's own fzf bindings: `__listen`, `__redraw` and `__switch <session> [pane]`."""
    import os

    from switchboard import sidebar

    if argv[0] == "__listen":
        sidebar.listen()
    elif argv[0] == "__redraw":
        sys.stdout.write(sidebar.redraw(os.environ.get(sidebar.FOLDER, "")))
    else:
        session, pane = [*argv[1:], "", ""][:2]
        sys.stdout.write(sidebar.switch(session, pane))
    return 0


def cmd_preview(args: list[str]) -> int:
    """The picker's preview, `__preview <session> [pane]`, sized by fzf's `$FZF_PREVIEW_LINES`."""
    import os

    from switchboard import preview

    lines = os.environ.get("FZF_PREVIEW_LINES", "")
    height = int(lines) if lines.isdecimal() else preview.HEIGHT
    session, pane = [*args, "", ""][:2]
    sys.stdout.write(preview.show(session, height, pane))
    return 0


def cmd_seen(args) -> int:
    from switchboard import attention

    session = args.session or attention.current_session()
    if session:
        attention.seen(session)
    return 0


def cmd_refresh(args) -> int:
    from switchboard import attention

    attention.refresh()
    return 0
