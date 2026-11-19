# switchboard

[![CI](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml)

A keyboard-only tmux session switcher for people who run coding agents in tmux: Claude Code, Codex and Pi. It groups your sessions by git repository, and shows which agents are working, which are done, and which need you.

There are five pieces:

- **The picker.** One key opens it in a popup. It lists every session as repo → worktree → agents, with each agent's state, and previews the highlighted session. `j`/`k` and Enter switch, and `q` closes. No mouse.
- **The sidebar.** Another key opens the picker's list, compact, in a narrow pane on the left of the window. It stays open and redraws itself as states change.
- **The status-bar segment.** It names the other sessions whose agents need you or are done.
- **The alert.** A tmux message on every client and a short sound, when an agent in a session no one is looking at needs you or finishes.
- **The hook.** Each agent runs `switchboard hook [--agent NAME] <event>` on its events, and that keeps its state up to date. Claude Code and Codex run it from their hooks, and Pi from an extension. Other agents can be [added](#adding-an-agent).

State lives in tmux pane options on each agent's pane. There's no daemon, no polling and no state file.

## The picker

```
j/k move · / search · tab fold · ↵ switch · q/esc close

▸ gadget  1 done
▾ widget  1 needs you · 1 working
│ ◉ main       ~2     ●
│   └ ● claude · win 1 · working
│   fix-login  ~1 ↑3  ●
│   ├ ● claude · win 0 · needs you
│   └ ○ teammate · win 2 · idle
▾ other
│   notes
```

The picker draws its icons from a [Nerd Font](https://www.nerdfonts.com): the sketch above stands in plain characters for them, and leaves out the dots' [colours](#states).

- **Repo headers** show the repo's name, or its [label](#project-labels), and how many of its sessions need you, are done or are working. A caret pointing down is open, and one pointing right is folded.
- **Worktree rows** show the branch (in "other", the session's name), its git status and the most urgent agent's state. `~2` is two uncommitted changes, and `↑3` is three commits not pushed. A green circled dot marks the session you're in, and the cursor starts there.
- **Agent rows** sit under their worktree, in a softer colour, each starting with its state's dot. Each names the agent by its label, `claude`, `codex` or `pi`, or `teammate` for an agent-team teammate in its own pane, then the window it's in.
- **Order:** repos alphabetically, then "other" for sessions outside any repo. Within a repo, the default branch comes first, then the rest alphabetically.
- **The preview** on the right shows the session's folder, its windows with an agent's icon on the window that holds it, and the last lines of its most urgent agent's pane, or of its active pane when it has no agents. So you can see what an agent is asking before you switch.

Git status is read for every worktree at once, with a one-second limit. A slow or broken repo shows no status rather than holding up the list.

The picker's colours are Catppuccin Latte in light mode and Macchiato in dark mode, as in [wkt](https://github.com/wmxscott/wkt)'s picker. It chooses once when it starts: [`SWITCHBOARD_THEME`](#configuration) if it's `light` or `dark`, else theme-monitor's trigger file, else macOS's own setting. fzf's own colours, such as the highlighted line's, come from your fzf settings, as wkt's do.

### Keys

| Key | Does |
|---|---|
| `j` / `k` | Move |
| `/` | Search. After that, `j`, `k` and `q` type letters, and the arrow keys move |
| Tab | Fold or unfold the highlighted row's repo |
| Enter | Switch to the highlighted session. On an agent row, its session. On a repo header, nothing |
| `q` / Esc | Close. While searching, Esc clears the search and goes back to `j` and `k` |

The header shows the keys that work at the moment, and changes when you search.

## The sidebar

```
▸ gadget ●
▾ widget
│ ◉ main       ●
│   fix-login  ●
▾ other
│   notes
```

`prefix b` opens it in a 32-column pane down the left edge of the current window, full height, whichever pane you're in. Pressed again, it closes it, and the other panes get back the widths it took. The focus stays where it was.

- **It shows** the picker's list, compact: repo headers, and worktree rows with their state dot. Agents fold into the dot. There are no counts, no git status and no preview, and long names are cut short with `…`.
- **A folded repo** shows the dot of its most urgent state after its name, so a fold never hides a session that needs you. An open repo's header has no dot.
- **The keys** are the picker's: `j`/`k`, `/` to search, Tab to fold, and Enter or a double click to switch. Nothing in the sidebar closes it: `q` does nothing, and Esc only leaves a search. Close it with `prefix b` again, or Ctrl-C.
- **Enter switches** the client viewing the sidebar to the highlighted session. The sidebar stays in its window: it doesn't follow you to the other session.
- **It redraws live.** Every state change, every switch of session, and every `switchboard refresh` asks each open sidebar to reload. So does each session created or closed, with the hooks in [tmux setup](#tmux-setup). There's no polling.

Each sidebar's fzf listens on a local port, which it records with a random key in its pane's `@switchboard-sidebar` option. That option is also how `prefix b` finds the window's sidebar. A pane it has just opened holds `starting` until fzf records its port, and keeps the window's layout from before it in `@switchboard-layout`. If you split or close a pane while the sidebar is open, that layout no longer fits, and closing the sidebar leaves the widths as they are.

### The binding

```tmux
bind b run-shell "switchboard sidebar --toggle #{pane_id}"
```

`run-shell` gives the command no `$TMUX_PANE`, so the binding passes the pane in `#{pane_id}`, which tmux fills in. It prints nothing unless it fails. Pick any key you like.

### tmux-resurrect

[tmux-resurrect](https://github.com/tmux-plugins/tmux-resurrect) restores a sidebar as a running sidebar with this line:

```tmux
set -g @resurrect-processes '"~switchboard sidebar->switchboard sidebar"'
```

- **What it matches.** tmux-resurrect saves the command that each pane's shell is running. `prefix b` runs the sidebar under `sh`, so it saves as `<python> -m switchboard sidebar`, and a restored one as `<python> <path>/switchboard sidebar`. `~` matches `switchboard sidebar` anywhere in that command.
- **What it runs.** `->` types plain `switchboard sidebar` into the restored pane's shell, so `switchboard` must be on that shell's `PATH`.
- **The layout** comes back too, so the pane keeps its width and its place.
- **Other programs** go in the same quoted list, such as `'"~switchboard sidebar->switchboard sidebar" vim'`.

A restored sidebar runs in a shell, so Ctrl-C leaves that shell open where a sidebar from `prefix b` would close its pane. `prefix b` closes either.

## States

| Picker | Status bar | State | Means |
|---|---|---|---|
| red dot | ▲ | needs you | A permission prompt or a question is waiting for you: a tool approval, `AskUserQuestion`, a plan to approve, or an MCP server asking for input |
| green dot | ✓ | done | It finished a turn while you were in another session |
| orange dot | | working | It's busy on a turn |
| hollow green dot | | idle | It's waiting for a prompt, and you've seen it |

In the picker, green means finished and a filled dot means you haven't seen it yet.

- **Starting Claude Code** shows it idle at once, before its first prompt. So does `claude --continue` in a restored pane.
- **Sending a prompt** makes an agent working.
- **A permission prompt or a question** makes it needs you. That includes a subagent's, which shows on its lead's pane. **It stays when you visit,** and clears once you answer and the agent carries on, or you send a new prompt.
- **Finishing a turn** makes it done. If a client is already viewing that session, it goes straight to idle with no alert, since you watched it finish.
- **Visiting the session** turns done into idle.
- **Teammates** raise ▲ and alert like any agent, but never become done, since they go idle between messages all the time.
- **Claude Code exiting** clears the state. `/clear` and `/resume` make it idle.

### A slow approved command

After you approve a slow command, such as a test run or a build, ▲ stays until the command finishes. Claude Code sends no event between your approval and the end of the tool, so switchboard can't tell that you've answered.

To soften this, your status bar never lists the session you're in. While you watch the build, nothing shows for it. ▲ only appears if you switch away before it ends. With several clients, each one's status bar leaves out its own session.

Interrupting a turn sends no event either, so the agent shows working until Claude Code's idle notification turns it idle.

## Requirements

- **tmux 3.8 or later.** The status-bar segment uses tmux 3.8's theme colours.
- **[fzf](https://github.com/junegunn/fzf) 0.59 or later**, for the picker and the sidebar.
- **A [Nerd Font](https://www.nerdfonts.com)** in your terminal, for the picker's and the sidebar's icons.
- **Python 3.11 or later**, when installing from source.
- **A coding agent**, for agent state. Without one, switchboard is a plain session switcher:
  - **Claude Code**
  - **Codex 0.170 or later**, started with `codex --no-daemon` (see [Codex setup](#codex-setup))
  - **Pi 1.1.0 or later**
- **macOS, for the sound.** It plays through `afplay`. Elsewhere the alert is silent.

## Install

### Homebrew

```sh
brew install wmxscott/tap/switchboard
```

Homebrew installs tmux and fzf too.

### From source

```sh
uv tool install git+https://github.com/wmxscott/switchboard
# or: pipx install git+https://github.com/wmxscott/switchboard
```

## tmux setup

Add these lines to your tmux config:

```tmux
bind w display-popup -E -w 90% -h 80% -d "#{pane_current_path}" switchboard
bind b run-shell "switchboard sidebar --toggle #{pane_id}"
set-hook -g client-session-changed 'run-shell -b "switchboard seen #{q:session_name}"'
set-hook -g session-created 'run-shell -b "switchboard refresh"'
set-hook -g session-closed 'run-shell -b "switchboard refresh"'
run-shell -b "switchboard refresh"
set -g status-right "#{E:@attention}"
set -g status-right-length 80
```

- **`prefix w`** opens the picker in a popup. Pick any key you like.
- **`prefix b`** opens or closes [the sidebar](#the-sidebar).
- **`client-session-changed`** runs `switchboard seen` for the session you've switched to, which marks its done agents seen. `#{q:…}` quotes the name for the shell, so names with spaces, quotes or `$` are safe.
- **`session-created` and `session-closed`** refresh when a session comes or goes, so open sidebars add or drop it, and no status bar keeps naming a closed session. Without them, that waits for the next state change.
- **`switchboard refresh`** fills the status bar when the config loads. After that, every change refreshes it.
- **`#{E:@attention}`** shows the segment. switchboard sets `@attention` on each session, as a format with tmux's theme colours, which `E:` expands. To keep an existing `status-right`, add `#{E:@attention}` to it rather than replacing it.
- **`status-right-length`** defaults to 40, which cuts the list short. The segment needs about 60, plus whatever else is on the right.

The segment names sessions, needs you first, then done:

```
▲²✓ widget/fix-login  ✓ gadget/main  ✓² widget/docs
```

- **Each session** sits in the group of its most urgent agent, with a mark for each state its agents are in. Here, two agents in `widget/fix-login` need you and a third is done.
- **A superscript** counts the agents in that state, when there's more than one. A single agent shows a bare mark.
- **When the names don't fit** in about 60 columns, counts included, it switches to counting sessions: `▲ 4 need you  ✓ 3 done  prefix w`.

## Claude Code setup

The `switchboard` plugin from [ai-toolkit](https://github.com/wmxscott/ai-toolkit) wires the hooks:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install switchboard@ai-toolkit
```

To wire them yourself, add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "switchboard hook SessionStart" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "switchboard hook UserPromptSubmit" }] }
    ],
    "PreToolUse": [
      {
        "matcher": "AskUserQuestion|ExitPlanMode",
        "hooks": [{ "type": "command", "command": "switchboard hook PreToolUse" }]
      }
    ],
    "PostToolUse": [
      { "hooks": [{ "type": "command", "command": "switchboard hook PostToolUse" }] }
    ],
    "PostToolUseFailure": [
      { "hooks": [{ "type": "command", "command": "switchboard hook PostToolUseFailure" }] }
    ],
    "PermissionRequest": [
      { "hooks": [{ "type": "command", "command": "switchboard hook PermissionRequest" }] }
    ],
    "Notification": [
      { "hooks": [{ "type": "command", "command": "switchboard hook Notification" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "switchboard hook Stop" }] }
    ],
    "StopFailure": [
      { "hooks": [{ "type": "command", "command": "switchboard hook StopFailure" }] }
    ],
    "SubagentStop": [
      { "hooks": [{ "type": "command", "command": "switchboard hook SubagentStop" }] }
    ],
    "TeammateIdle": [
      { "hooks": [{ "type": "command", "command": "switchboard hook TeammateIdle" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "switchboard hook SessionEnd" }] }
    ]
  }
}
```

Sessions that are already running may need a restart to pick them up.

`switchboard hook` reads the hook's JSON on stdin and the pane from `$TMUX_PANE`. It never prints, never blocks and always exits 0. A bad payload, or a tmux that doesn't answer, leaves a stale icon at worst, never a broken turn. Outside tmux it does nothing. An event that changes nothing costs one Python start and one tmux call, a few tens of milliseconds.

## Codex setup

The same `switchboard` plugin from [ai-toolkit](https://github.com/wmxscott/ai-toolkit) wires Codex's hooks:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add switchboard@ai-toolkit
```

- **Trust the hooks.** Codex runs a plugin's hooks only once you trust them. Start Codex and review them when it asks, or open `/hooks`. It asks again after an update changes them.
- **Start Codex with `codex --no-daemon`.** Since 0.157, Codex runs its sessions in a shared background daemon by default. The daemon keeps the environment of the terminal that first started it, so its hooks report that terminal's tmux pane. switchboard ignores those events rather than show them on the wrong pane, so only `--no-daemon` sessions are tracked.
- **Codex started inside a Claude Code session** isn't tracked, since it would report Claude's pane.

A Codex session shows in the picker as `codex`. To wire the hooks yourself, run `switchboard hook --agent codex <event>` on SessionStart, UserPromptSubmit, PreToolUse (for `request_user_input`), PermissionRequest, PostToolUse, Stop, SubagentStop, Interrupt and SessionEnd.

The limits:

- **A failed turn** shows working until your next prompt. Codex sends no event for it.
- **An MCP server asking for input** never shows needs you. Codex has no hook for it.
- **The auto-reviewer** can flash needs you for a moment before it approves a call, since Codex asks for permission before the reviewer decides.
- **No agent teams.** Codex has none, so a Codex pane is never a teammate.

## Pi setup

The [ai-toolkit](https://github.com/wmxscott/ai-toolkit) Pi package has a switchboard extension:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

If you have the package already, `pi update --extensions` picks up the extension. The package also brings skills, other extensions and themes. [Its Pi README](https://github.com/wmxscott/ai-toolkit/blob/main/pi/README.md) shows how to load only part of it.

The extension sends each event to `switchboard hook --agent pi <event>`, with the event as JSON on stdin. It acts only in Pi's terminal UI inside tmux, and never waits for switchboard except briefly when you quit. A Pi session shows in the picker as `pi`.

| Event | State |
|---|---|
| `session_start` | Idle, or working if a run is going |
| `agent_start` | Working |
| `ui_prompt_start`, `ui_prompt_end` | Needs you while an extension's dialog is open |
| `plannotator_opened`, `plannotator_closed` | Needs you while a Plannotator review is open |
| `agent_settled` | Done, or idle if you aborted the run |
| `session_shutdown` | On quit, cleared |

The limits:

- **Needs you** comes only from extension dialogs, such as a permission gate's, and from Plannotator reviews. Pi has no permission prompts of its own, and its built-in waits, such as the trust prompt, `/login` and MCP OAuth, send no event.
- **An extension's custom UI** shows needs you even when it isn't waiting for you.
- **An aborted run** goes idle, not done, and doesn't alert.

## Commands

| Command | |
|---|---|
| `switchboard` | Open the picker. It runs only inside tmux, and exits 1 elsewhere |
| `switchboard hook [--agent NAME] <event>` | An agent's hook, with the event's JSON on stdin. The agent is `claude` by default. See [Claude Code setup](#claude-code-setup) and [Adding an agent](#adding-an-agent) |
| `switchboard state <verb> [--agent NAME]` | Set this pane's agent state, for a tool with no adapter. See [Without an adapter](#without-an-adapter) |
| `switchboard seen [session]` | Turn a session's done agents idle, then refresh. By default, the current session |
| `switchboard refresh` | Rebuild every session's `@attention`, and redraw every open sidebar |
| `switchboard sidebar` | Show [the sidebar](#the-sidebar) in this pane, until Ctrl-C |
| `switchboard sidebar --toggle [PANE]` | Close the sidebar in `PANE`'s window, or open one down the window's left edge. By default, this pane. It prints nothing unless it fails |

Outside tmux, the picker and both sidebar commands exit 1 with a message. Every other command exits 0 and does nothing, and `state` still checks its arguments.

## Project labels

Repo headers can carry an icon and a label from [herdr-projects](https://github.com/wmxscott/herdr-projects)' project list. The list is optional: without it, or if it can't be read, headers show the repo's folder name. switchboard only reads it, from:

```
~/.config/herdr/plugins/config/herdr-projects/projects.toml
```

It follows `$XDG_CONFIG_HOME`. The shape:

```toml
[[groups]]
name = "tools"
icon = "🔧"

[[projects]]
name = "widget"
group = "tools"
path = "~/src/widget"
```

That labels the repo at `~/src/widget` as `🔧 tools/widget`. A project's own `icon` wins over its group's. A project's `path` can be any checkout or worktree of the repo, and labels all of it. Entries without a `name`, or with a relative `path`, are skipped.

## Configuration

| Variable | |
|---|---|
| `SWITCHBOARD_THEME` | The picker's colours: `light`, `dark` or `auto`. `auto`, the default, follows [theme-monitor](https://github.com/wmxscott/theme-monitor)'s trigger file, `$XDG_DATA_HOME/theme-monitor/theme-change.trigger`, else macOS's setting, else light |
| `SWITCHBOARD_SOUND` | The alert's sound file. Empty turns the sound off. By default, macOS's Glass sound. The hook plays it, so set it where Claude Code will see it, such as your shell profile |
| `XDG_CONFIG_HOME` | Where the [project list](#project-labels) is looked for, instead of `~/.config` |
| `CLAUDE_CONFIG_DIR` | Where Claude Code keeps its team configs, which tell a teammate's pane from its lead's. By default, `~/.claude` |

## How sessions map to worktrees

switchboard follows [wkt](https://github.com/wmxscott/wkt)'s rule. A session belongs to:

1. The worktree in its `@wkt-worktree` session option. wkt sets it on every session it opens.
2. Otherwise, the worktree that contains the session's folder (`session_path`). This covers sessions you made yourself, and sessions restored by tmux-resurrect, which drops `@` options.

Worktrees are grouped by their git common dir, so two repos in folders with the same name never mix, and a `.bare` layout groups like any other. wkt names sessions `<repo>/<branch>`. The picker shows the branch, so the session's name doesn't matter there, but the status bar and the alert use it.

A session in no git repository, such as one in `~`, goes in "other".

## Adding an agent

Each agent has an adapter: a module, `src/switchboard/agents/<name>.py`, that turns the agent's events into changes to its pane's state. Adding an agent takes that module and its tests, and nothing else in switchboard. The agent's own side, its hooks or extension, ships with the agent or a plugin, not here.

### How an event arrives

1. The agent runs `switchboard hook --agent <name> <event>` from its own pane, with the event as a JSON object on stdin. Without an `<event>` argument, the payload's `hook_event_name` names it.
2. switchboard imports `switchboard.agents.<name>`. An unknown name does nothing.
3. The adapter turns the event into verbs. switchboard reads the pane once, applies the verbs, and writes once if anything changed. A change to needs you or done alerts when no client is viewing the session, and every change refreshes the status bar.

- **The pane guard.** For any agent but Claude, an event counts only if the hook runs inside the pane, as a descendant of the pane's process. Otherwise it's dropped, so an agent that runs its hooks from a daemon never writes to the wrong pane.
- **In order.** Each call takes a few tens of milliseconds. An integration that mustn't block, such as an extension, can run it in the background, one call at a time, so the events keep their order.

### The adapter

An adapter module has:

- **`HANDLED`:** the event names it acts on. Any other event is dropped before tmux is touched.
- **`verbs(event, payload, state)`:** the verbs the event applies to its pane, as a list, in order. `payload` is the event's JSON object. `state` is the pane's `core.State` as stored: `pane`, `role`, `turn`, and `pending`, a tuple of keys. On a pane with nothing stored, `role` and `turn` are empty, and the verbs treat it as an idle lead.
- **`early(event, payload)`, optional:** decides from the event alone, before the pane is read. `[]` drops the event, `[core.END]` ends the agent, other verbs apply after the read, and `None` hands the event to `verbs`.

The verbs, from `switchboard.core`:

| Verb | Does |
|---|---|
| `START` | A new agent process: a lead, idle, with nothing pending |
| `WORKING`, `IDLE` | Set the turn |
| `DONE` | Set the turn done, or idle when a client is viewing the session or the pane is a teammate |
| `needs(key)` | Add a pending prompt. The agent needs you while any is pending. The key is `lead` for the agent's own, or a subagent's id |
| `resolve(key)` | Remove a pending prompt. `RESOLVE_ALL` removes every one |
| `TEAMMATE` | Mark the pane an agent-team teammate |
| `END` | The agent has gone: unset every `@switchboard-*` option |

For example, `src/switchboard/agents/acme.py`, for an agent whose plugin sends `start`, `prompt`, `ask`, `answer`, `stop` and `exit`:

```python
"""Acme: the events its plugin forwards, each with its fields on stdin."""

from __future__ import annotations

from switchboard import core

HANDLED = frozenset({"start", "prompt", "ask", "answer", "stop", "exit"})


def early(event: str, payload: dict) -> list[core.Verb] | None:
    return [core.END] if event == "exit" else None


def verbs(event: str, payload: dict, state: core.State) -> list[core.Verb]:
    match event:
        case "start":
            return [core.START]
        case "prompt":
            return [core.WORKING, core.RESOLVE_ALL]
        case "ask":
            return [core.needs("lead")]
        case "answer":
            return [core.resolve("lead")]
        case "stop":
            return [core.RESOLVE_ALL, core.DONE]
    return []
```

`claude.py`, `codex.py` and `pi.py` in the same folder are fuller examples. `codex.py` reuses Claude's mapping and changes only what differs, and its `Interrupt` reads `state.turn`.

### Registering it

There's no list to add it to. `switchboard hook --agent acme` imports `switchboard.agents.acme`, so the module's name is the agent's name, and the picker shows it on the agent's rows. It must be a valid Python identifier that doesn't start with `_`.

### The contract

`switchboard hook` never prints and always exits 0 at runtime, so it can never break an agent's turn. Some agents pass a hook's output to the model, so this matters. switchboard swallows anything an adapter raises, and drops the event. An adapter keeps the rest of the contract:

- **It never prints.**
- **It never runs tmux.** switchboard makes the one read and the one write.
- **It's fast.** It runs on every event, often on every tool call, so it imports little and does no slow work.

### Tests

An adapter's tests go in `tests/agents/test_<name>.py`. The `drive` fixture in `tests/agents/conftest.py` sends events through `switchboard hook --agent <name>`, against stub `tmux` and `ps`:

- **`drive(name, field)`** returns a `Driver` for the agent, whose payloads carry the event's name in `field`.
- **`stored(state, viewed=False, inside=True)`** sets the pane's stored state, written `role:turn:pending`, as in `lead:working:lead`. `viewed` puts a client on the pane's session, and `inside=False` runs the hook outside the pane.
- **`fire(event, **fields)`** sends the event, with `fields` in its payload.
- **`after()`** is the state written, or `None` for no write. It also checks that the write labels the pane with the agent.
- **`written()`, `calls()` and `alerts()`** return the options written, the tmux calls and the alerts sent.

```python
import pytest


@pytest.fixture
def acme(drive):
    return drive("acme", "event")


@pytest.mark.parametrize(
    ("event", "before", "expected"),
    [
        ("start", "lead:working:lead", "lead:idle:"),
        ("prompt", "lead:done:", "lead:working:"),
        ("ask", "lead:working:", "lead:working:lead"),
        ("stop", "lead:working:lead", "lead:done:"),
        ("stop", "lead:done:", None),
    ],
)
def test_event_mapping(acme, event, before, expected):
    acme.stored(before)
    acme.fire(event)
    assert acme.after() == expected


def test_unknown_events_never_call_tmux(acme):
    acme.fire("compact")
    assert acme.calls() == []


def test_events_from_outside_the_pane_are_dropped(acme):
    acme.stored("lead:idle:", inside=False)
    acme.fire("prompt")
    assert acme.after() is None
```

Cover every event the adapter handles, the events it drops, and an event from outside the pane. `tests/agents/test_codex.py` and `tests/agents/test_pi.py` are complete examples.

### Without an adapter

A script, or a tool that knows its own state at each point, can skip the adapter and set the state from its pane:

```sh
switchboard state working --agent build
make test
switchboard state done --agent build
```

- **The verbs** are `start`, `working`, `done`, `idle`, `needs KEY`, `resolve KEY`, `resolve all` and `end`, as above. `end` stops tracking the pane.
- **`--agent`** labels the pane in the picker. Without it, the label is `claude`. Any other name turns on the pane guard, so run `state` from inside the pane.
- **The contract** is the hook's: it never prints and always exits 0 at runtime. Only malformed arguments exit 2, with one line on stderr.

Write an adapter instead when the state depends on the event's payload or on the stored state, such as a subagent's prompt or an interrupt, or when other people will use the integration.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

The tests run against a temporary `HOME`, with stub `tmux`, `fzf` and `afplay` first on `PATH`, so they never touch a real tmux server, fzf, Claude Code or your files. To try a change against real tmux, use a throwaway server, such as `tmux -L test -f /dev/null`, and kill it afterwards.

## License

[MIT](LICENSE)
