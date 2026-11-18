# switchboard

[![CI](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml/badge.svg)](https://github.com/wmxscott/switchboard/actions/workflows/ci.yml)

A keyboard-only tmux session switcher for people who run Claude Code agents in tmux. It groups your sessions by git repository, and shows which agents are working, which are done, and which need you.

There are four pieces:

- **The picker.** One key opens it in a popup. It lists every session as repo → worktree → agents, with each agent's state, and previews the highlighted session. `j`/`k` and Enter switch, and `q` closes. No mouse.
- **The status-bar segment.** It names the other sessions whose agents need you or are done.
- **The alert.** A tmux message on every client and a short sound, when an agent in a session no one is looking at needs you or finishes.
- **The hook.** Claude Code runs `switchboard hook <event>` on its hook events, and that keeps each agent's state up to date.

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
- **Agent rows** sit under their worktree, in a softer colour, each starting with its state's dot: `claude` for a Claude Code session, or `teammate` for an agent-team teammate in its own pane, with the window it's in.
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
- **[fzf](https://github.com/junegunn/fzf) 0.59 or later**, for the picker.
- **A [Nerd Font](https://www.nerdfonts.com)** in your terminal, for the picker's icons.
- **Python 3.11 or later**, when installing from source.
- **Claude Code**, for agent state. Without it, switchboard is a plain session switcher.
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
set-hook -g client-session-changed 'run-shell -b "switchboard seen #{q:session_name}"'
run-shell -b "switchboard refresh"
set -g status-right "#{E:@attention}"
set -g status-right-length 80
```

- **`prefix w`** opens the picker in a popup. Pick any key you like.
- **`client-session-changed`** runs `switchboard seen` for the session you've switched to, which marks its done agents seen. `#{q:…}` quotes the name for the shell, so names with spaces, quotes or `$` are safe.
- **`switchboard refresh`** fills the status bar when the config loads. After that, every change refreshes it.
- **`#{E:@attention}`** shows the segment. switchboard sets `@attention` on each session, as a format with tmux's theme colours, which `E:` expands. To keep an existing `status-right`, add `#{E:@attention}` to it rather than replacing it.
- **`status-right-length`** defaults to 40, which cuts the list short. The segment needs about 60, plus whatever else is on the right.

The segment names sessions, needs you first, then done:

```
▲ widget/fix-login  ✓ gadget/main
```

When the names don't fit in about 60 columns, it switches to counts: `▲ 4 need you  ✓ 3 done  prefix w`.

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

## Commands

| Command | |
|---|---|
| `switchboard` | Open the picker. It runs only inside tmux, and exits 1 elsewhere |
| `switchboard hook <event>` | The Claude Code hook. See above |
| `switchboard seen [session]` | Turn a session's done agents idle, then refresh. By default, the current session |
| `switchboard refresh` | Rebuild every session's `@attention` |

Outside tmux, every command but the picker exits 0 and does nothing.

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

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

The tests run against a temporary `HOME`, with stub `tmux`, `fzf` and `afplay` first on `PATH`, so they never touch a real tmux server, fzf, Claude Code or your files. To try a change against real tmux, use a throwaway server, such as `tmux -L test -f /dev/null`, and kill it afterwards.

## License

[MIT](LICENSE)
