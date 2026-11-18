# switchboard: design

**Status:** approved by the user on 2026-11-18.

## Why

The user is moving their daily terminal setup from Herdr to tmux, in five projects:
1. the tmux core, in `wmxscott/dotfiles`
2. wkt's tmux mode, released as wkt 2.1.0
3. this project
4. ports of herdr-projects and herdr-launchpad
5. removing Herdr, which happens only on the user's say-so

They want a stable environment they own, built on mature tools, small scripts and few pinned plugins, rather than one that changes with every new tool.

In the new setup, a worktree is a tmux session and a Herdr tab is a tmux window. wkt makes worktrees and opens them as sessions named `<repo>/<branch>`.

What's still missing is the part of Herdr the user leans on all day. In the user's words: "I look at the spaces panel… I do `prefix w` and `j/k` to move to the workspace and `enter` to switch. Typically, I'm triggered by the agent status running in that workspace."

When an agent needs them or finishes, they notice it in this order:
1. the workspace list
2. the toast
3. the agents panel, which they hardly use

switchboard brings the first two to tmux:
- **The switcher:** a picker of every worktree session grouped by repo, showing each session's Claude agents and their state.
- **Agent tracking:** follows each Claude agent's state through Claude Code's hooks.
- **The status bar segment:** names the worktrees that need you.
- **The alert:** a message with a short sound.

## Goals

- `prefix w` opens a picker of every worktree session, grouped by repo. Each worktree shows its Claude agents and their state. `j`/`k` and Enter switch, as in Herdr.
- **Each Claude agent's state is tracked:**
  - working
  - needs you: a permission prompt or a question
  - done: finished, and you haven't looked since
  - idle
- The status bar names the worktrees that need you or are done, and switches to counts when crowded.
- An alert, a tmux message plus a short sound, fires when an agent in a session you're not looking at turns "needs you" or "done".
- Visiting a session turns its "done" agents idle.

## Non-goals

- Selecting an agent or a window from the switcher. Agent rows aren't selectable yet; jumping to an agent's window is a later step.
- Any agent other than Claude Code.
- An agents panel.
- macOS notification banners. Herdr's alerts were in-app (`delivery = "herdr"`).
- Managing the project list (icons, groups). That's project 4's port of herdr-projects. switchboard only reads the list.
- Worktrees without a session. `prefix W`, wkt's picker, covers those.
- Other machines. Over SSH, the remote machine runs its own copy.

## Anti-goals

Any of these counts as a failure, even if everything else works:

- **Any mouse use.** The user said: "no mouse at all, anywhere".
- **A daemon, a polling loop or state files.** Everything is driven by events.
- **A "needs you" or "done" that lingers** after it's been dealt with, or a stale "working" that never clears.
- **An alert or sound for the session you're looking at.**
- **Slowing Claude down.** Hooks must return fast and never block or fail a turn.
- **Breaking Claude when switchboard is missing, or outside tmux.** In both cases the hook does nothing, silently.
- **Touching Herdr's own Claude integration.** It keeps working while the user still uses Herdr.

## Decided by the user

### Name and how it's built
- **Name:** `switchboard`, in a public repo `wmxscott/switchboard`.
- **Built like pr-tracker:** Python and fzf, with flit packaging and a console script, installed from `wmxscott/tap`.

### Agent states
- **Sending a prompt** makes an agent working.
- **A permission prompt or a question** makes it needs you.
- **Finishing a turn** makes it done.
- **Switching to its session** turns done into idle.
- **"Needs you" stays when you visit,** and clears only when you answer and the agent works again.
- **Finishing while you're in that session** goes straight to idle, with no alert, since you watched it.
- **Claude exiting** clears the state.

### The switcher (mockup "B")
- **The popup:** `prefix w` opens a wide popup, with the list on the left and a preview of the highlighted worktree on the right.
- **The list has three levels:**
  - **Repo header:** the project's icon and `group/name` from herdr-projects' list, plus a summary such as "1 needs you". A repo not in the list shows its plain name, without an icon.
  - **Worktree rows:** one per open tmux session, showing the branch, its git status (`~1 ↑3`) and the most urgent agent state icon. The order of urgency is ▲ needs you, ✓ done, ● working, ○ idle. `▸` marks the session you're in.
  - **Agent rows:** under each worktree, dimmed, such as `claude · win 1 · needs you`. They can't be picked.
- **Grouping:** worktrees are grouped by git repository (the git common dir), so two folders with the same name never collide.
- **Order:** stable. Repos are alphabetical; within each, the default branch comes first, then the rest alphabetically. A session that isn't in a git repo, for example one in `~`, goes in an "other" group at the end.
- **Keys** (no mouse, and fzf's search is off until asked for):
  - `j`/`k` move.
  - Enter switches.
  - Tab folds or unfolds a repo.
  - `/` starts searching.
  - Esc closes.
- **The preview:**
  - the session's name and folder
  - its windows, with the agent icon on the window that holds an agent
  - the last lines of its most urgent agent's pane, so you can see what it's waiting on before switching

### Status bar ("A3")
- **Normally:** the right side names the worktrees that need you, then those that are done, for example `▲ dotfiles/main  ✓ pr-tracker/feat/herdr-app`.
- **When the names stop fitting:** it switches to counts, `▲ 4 need you  ✓ 3 done  prefix w`.
- **The slot:** it fills the `@attention` user option, which the tmux core already shows (`status-right "#{E:@attention}"`).

### The alert
- **What and where:** a tmux message, which `message-style` already places on the right 40% of the status bar.
- **Who sees it:** each client that isn't viewing the agent's session.
- **Sound:** a short one plays with it.
- **When:** it fires only on a change to "needs you" or "done".

### A slow approved command (from the builder check)
Claude sends no event between "the user approved" and "the tool finished". So after you approve a slow command, such as a test run or a build, ▲ stays until the command ends.
- **The user accepted this,** and it's documented and tested as a limitation.
- **To soften it, the status bar never lists the session you're in.** While you watch the build, nothing shows for it; ▲ only appears if you switch away before it finishes. With several clients, each client's status bar leaves out its own session. One way: keep `@attention` per session rather than global.
- **Rejected:** treating a visit to the agent's pane as an answer. You could look, leave without answering, and lose the ▲ while Claude still waits.

### Agent-team teammates (from the builder check)
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is on in the user's Claude settings. Inside tmux, Claude opens each teammate in its own pane, as a separate Claude process with its own hooks, which goes idle between messages all the time.
- **Shown:** teammates appear as agent rows under their worktree, labelled as teammates.
- **▲ only:** a teammate's permission prompt or question raises ▲ like any other.
- **No "done":** only the lead agent ever becomes "done" or gets the alert, so idle teammates never ring.
- **Detection:** how a teammate is told apart from a lead, from the hook payload or the environment, is for the builder to find out.

### The project list
- **Where it's read from:** `~/.config/herdr/plugins/config/herdr-projects/projects.toml`. Project 4 decides where the list lives long-term.
- **Its shape:**
  - `[[groups]]`, each with `name` and `icon`
  - `[[projects]]`, each with `name`, `group`, `icon` and `path`
- **Labels:** `<icon> <group>/<name>`. A project's own icon wins over its group's.

## My calls

These weren't discussed. The user can overrule them when reviewing.

1. **Where state lives:**
   - Each Claude agent's state is a tmux **pane option** on its own pane, for example `@switchboard-state`, plus a timestamp.
   - It's set with `$TMUX_PANE` from the hook's environment.
   - There are no files, and the state disappears with the pane.
   - tmux-resurrect doesn't save pane options, so restored Claude panes start with no state, which shows as idle.
2. **Hook wiring:**
   - A new ai-toolkit plugin, `switchboard`, like pr-tracker's, wires Claude Code's hook events to `switchboard hook <event>`.
   - If `switchboard` isn't installed or `$TMUX_PANE` is unset, it exits 0 at once.
   - **Subagents run in the lead's pane, and their prompts appear there.** So a subagent's permission prompt or question raises ▲ too. The builder check found that ignoring every `agent_id` would miss these, or leave them stuck.
     - **Tracking:** the pane keeps its pending prompts keyed by agent (the lead, or each subagent's `agent_id`).
     - **Clearing:** a prompt clears on that same agent's next tool event or its `SubagentStop`, or on the lead's `UserPromptSubmit` or `Stop`. One parallel subagent never clears another's prompt.
     - **"Needs you"** while any prompt is pending.
     - **Turn ends with background subagents still running:** the lead's `Stop` still makes it "done" and alerts. If Claude picks up again when they finish, it works, then becomes done and alerts again. That matches what Claude actually did.
     - **Speed:** the common case, a tool event with nothing pending, must stay fast. A cheap check before the full work is the builder's call.
3. **Which events mean what:**

   | Event | State |
   |---|---|
   | `UserPromptSubmit` | working |
   | `PermissionRequest`; `Notification` of type `permission_prompt` or `elicitation_dialog`; `PreToolUse` for `AskUserQuestion` | needs you |
   | `PostToolUse` and `PostToolUseFailure` | working, when the state was "needs you" |
   | `Stop` | done, or idle if a client is viewing the session |
   | `Notification` of type `idle_prompt` | idle, when the state was "working" |
   | `SessionEnd` | clear |

   The `idle_prompt` row clears a "working" that a user interrupt left behind. Claude fires no `Stop` on an interrupt.
4. **Commands:**
   - `switchboard`: the picker.
   - `switchboard hook <event>`: called by Claude.
   - `switchboard seen`: called by a tmux `client-session-changed` hook in the dotfiles. It turns the new session's done agents idle and refreshes `@attention`.
   - `switchboard refresh`: rebuilds `@attention` from the panes. The dotfiles run it once when the config loads, and every other command calls it after changing state.
5. **The tmux side lives in the user's dotfiles:**
   - the `prefix w` binding, a `display-popup` like `prefix W`, replacing `choose-tree`
   - the `client-session-changed` hook
   - the refresh on load

   The README shows the lines for anyone else.
6. **Pinning the client:** like wkt (its S21), the picker reads `#{client_name}` when it starts and switches with `switch-client -c`. From a popup, an unpinned `switch-client` can move the wrong client.
7. **Matching sessions to worktrees** follows wkt's documented rule: the `@wkt-worktree` tag first, else a `session_path` that's inside a worktree. A session matching nothing goes in "other".
8. **Enter on an agent row** switches to that agent's worktree session, the same as Enter on the worktree row. Agents still can't be picked on their own.
9. **The sound** is macOS's `afplay` with a system sound in the background, never blocking. `SWITCHBOARD_SOUND` changes it, and an empty value turns it off. On other systems there's no sound.
10. **Dependencies:** stdlib only, as pr-tracker does. Python 3.11+, tmux 3.8+, and fzf, at whatever version the key bindings need.

## Constraints

- **Speed:** hooks run on every prompt and tool call, so `switchboard hook` must finish in well under a tenth of a second for the common events. Python's startup is the budget; no network, and no git calls in the hook.
- **Testing:** pytest, with stub `tmux` and `fzf` executables first on `PATH`, as wkt's bats tests do. The tests never touch a real tmux server, Claude or the user's files. Real-tmux checks run only on a throwaway `tmux -L <name> -f /dev/null` server.
- **The user's tmux:**
  - 3.8, with `detach-on-destroy off`
  - Catppuccin theme colours named `themeblue`, `themeyellow` and so on, in `theme.conf`
  - `display-popup` doesn't expand `#{…}` in its command, though `-d` does
- **Public repo:** no personal names, paths or machine details.
- **House style:** short, plain sentences in docs. No narrative code comments; comment only what code can't say.
- **Releases:** go through the tap, as for pr-tracker and wkt.

## Left to the builder

- The exact layout of rows and preview, the colours, and the width threshold where the status bar switches to counts.
- How git status is gathered quickly enough for many worktrees, for example concurrently with a timeout, or skipped for a slow repo.
- The exact pane-option names and the timestamp format.
- Which system sound plays by default.
- How the hook is structured so the common events stay fast.

## Done when

- **Code:** switchboard is released through the tap with its tests green, the ai-toolkit plugin is merged, and the dotfiles bindings are merged.
- **Checked by the user in Ghostty:**
  - `prefix w` lists their worktree sessions grouped by repo, with project icons, and `j`/`k`/Enter switch.
  - A Claude agent in another session asking for permission shows ▲ in the status bar, shows an alert with a sound, and clears once answered.
  - A finished agent shows ✓, and turns idle after a visit.
