# switchboard

[![CI](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml)

A tmux session switcher for people who run Claude Code agents in their sessions. It shows which agents are working, which are done, and which need you.

**Under construction.** Only the command-line skeleton exists so far. Every command is a stub.

## What it will be

- **A picker** in a tmux popup: every worktree session, grouped by git repository, with each session's Claude Code agents and their state. Keyboard only.
- **A status-bar segment** naming the sessions whose agents need you or are done.
- **An alert,** a tmux message with a short sound, when an agent in a session you're not looking at needs you or finishes.

Agent state comes from Claude Code's hooks and lives in tmux pane options. There's no daemon, no polling and no state file.

## Install

### From source

Needs Python 3.11 or later, tmux and [fzf](https://github.com/junegunn/fzf) 0.59 or later.

```sh
uv tool install git+https://github.com/wmxscott/switchboard
# or: pipx install git+https://github.com/wmxscott/switchboard
```

## Commands

| Command | |
|---|---|
| `switchboard` | The picker |
| `switchboard hook <event>` | The Claude Code hook. Reads the hook JSON on stdin, never prints, and always exits 0 |
| `switchboard seen` | Marks the current session's finished agents as seen. Run by a tmux hook |
| `switchboard refresh` | Rebuilds the status-bar segment for every session |

Outside tmux, every command but the picker exits 0 and does nothing.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

The tests run against a temporary `HOME`, with stub `tmux` and `fzf` first on `PATH`, so they never touch a real tmux server, fzf, Claude Code or your files.

## License

[MIT](LICENSE)
