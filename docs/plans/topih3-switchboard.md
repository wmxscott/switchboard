# Plan: switchboard

| | |
|---|---|
| **Status** | landed. Only the user's Ghostty checks are left |
| **Updated** | 2026-11-18 |
| **Tracker** | — |
| **Related** | [approved design](../superpowers/specs/2026-11-18-switchboard-design.md); wkt's `docs/plans/too7nn-tmux-mode.md` (S5, S19, S21); dotfiles `docs/superpowers/specs/2026-11-16-tmux-core-design.md` |

## Goal

`prefix w` opens switchboard, a keyboard-only picker of every tmux worktree session grouped by repo, with each session's Claude agents and their state. The status bar and an alert with a sound tell the user when an agent in another session needs them or is done. That replaces the Herdr spaces panel and toasts they rely on all day.

**Falsifiable:** after this plan, the user can go a day in tmux without Herdr and never miss an agent that needs them. They switch with `prefix w`, `j`/`k` and Enter, and the mouse is never needed.

### Done when

- [x] switchboard 1.0.0 is released through the tap. CI is green, and `gh-harden` requires its checks.
- [x] The ai-toolkit `switchboard` plugin is merged and installed on this machine.
- [x] The dotfiles bind `prefix w` to switchboard, run `switchboard seen` on `client-session-changed`, and refresh `@attention` on load.
- [ ] In the user's real tmux, in Ghostty:
  - `prefix w` lists worktree sessions grouped by repo, with project icons, and `j`/`k`/Enter switch.
  - A permission prompt in another session shows ▲ in the status bar, plus an alert and a sound. It clears once the agent works again.
  - A finished agent shows ✓, and turns idle once the user visits.

## Settled: do not re-derive

- **S1 The design is approved.** Read the design for the user's decisions: agent states and how they change, the switcher (mockup B), the status bar (A3), the alert, the project list, slow approved commands, teammates, and the "My calls" list. This plan doesn't repeat them; it cites them as Design §… by heading.
- **S2 Built like pr-tracker.**
  - flit packaging, `src/switchboard/`, and a `switchboard` console script
  - Python ≥3.11, stdlib only (`tomllib` reads `projects.toml`)
  - `uv` for development, pytest and ruff
  - CI that lints, tests on a Python matrix, smoke-tests the console script, and runs gitleaks
  - pr-tracker's `.github/workflows/` is the template.
- **S3 The repo exists and is hardened.**
  - `wmxscott/switchboard` was created 2026-11-18, public. `gh-harden switchboard` has run: squash-only PRs, code-owner review, signed commits, `v*` tags admin-only.
  - **No CI checks are required yet.** Once A1's CI exists, re-run `gh-harden switchboard <job names…>`.
  - The local clone is a `.bare` layout at `~/Developer/wmxscott/switchboard`.
  - Merges use `gh pr merge --squash --admin`, which the user allowed.
- **S4 tmux facts, from wkt's plan (S19, S21) and dotfiles PR #42.**
  - `display-popup` doesn't expand `#{…}` in its command, but `-d` does.
  - Inside a popup, `$TMUX` is set and `$TMUX_PANE` isn't. A plain `switch-client` or `display-message -p` acts on the most recently active client, so the picker reads `#{client_name}` at start and passes `switch-client -c` and `display-message -t`.
  - Target sessions by exact name (`-t "=<name>"`). `set-option` needs `-t "=<name>:"`.
  - Session paths are stored as given; resolve them with `realpath` before comparing.
  - tmux-resurrect drops `@` options.
- **S5 Matching sessions to worktrees:** wkt's documented rule. The `@wkt-worktree` session tag first; else a `session_path` that's inside a worktree. Repo identity is the git common dir (`git rev-parse --git-common-dir`, resolved).
- **S6 The project list** is `~/.config/herdr/plugins/config/herdr-projects/projects.toml`.
  - Its shape: `[[groups]]` with `name` and `icon`; `[[projects]]` with `name`, `group`, `icon` and `path`.
  - A project's icon wins over its group's. Labels read `<icon> <group>/<name>`.
  - A missing or invalid file means no labels, never an error in the picker.
- **S7 Claude Code hook facts. A3 must check these against Claude Code's current docs before relying on them.** *(Superseded by S10, which A3 verified.)*
  - **Events used:** `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `Stop`, `SubagentStop` and `SessionEnd`, possibly with `SubagentStart`.
  - **Payload:** JSON on stdin. It has `hook_event_name` and `session_id`, `agent_id` for subagents, and `notification_type` (or the like) on `Notification`.
  - **Notification types** seen in Claude Code 2.1.326's binary: `permission_prompt`, `idle_prompt`, `elicitation_dialog`, `agent_needs_input` and `agent_completed`. The last two may be how teammates and subagents report, so A3 investigates them.
  - **No event fires on a user interrupt or on approving a permission.** See Design § A slow approved command.
- **S8 Herdr's Claude hook** (`~/.claude/hooks/herdr-agent-state.sh`, from the user's private `tool-hooks` plugin) only reports `SessionStart` to Herdr, which works out the state another way. switchboard leaves it untouched, and the two run side by side.
- **S9 The tests never touch a real tmux server, fzf, Claude, or the user's files.** They use stub executables first on `PATH` (as wkt's `test/test_helper.bash` does) and a temporary `HOME`. Real-tmux checks run only on a throwaway server with `-f /dev/null` (`tmux -L <name>`, or `TMUX_TMPDIR` under `$TMPDIR`, because the scratchpad path is too long for a socket). That server is killed afterwards.

- **S10 Hook facts, verified in A3 (2026-11-18)** against the code.claude.com docs for hooks, sub-agents and agent teams, and the local Claude Code 2.1.327 binary:
  - **All nine S7 events exist,** plus `SubagentStart` (unused) and `TeammateIdle`. A failed API call ends the turn with `StopFailure`, not `Stop`. `Stop` doesn't fire on an interrupt.
  - **Payload:** subagents and in-process teammates carry `agent_id`/`agent_type`. `Notification` never carries `agent_id`; its type field is `notification_type`. `permission_prompt` repeats `PermissionRequest` about 6 s later, except for sandbox network requests. `elicitation_url_dialog` is another needs-input type. `agent_needs_input` and `agent_completed` belong to agent view's background sessions, are answered elsewhere, and are ignored.
  - **Needs the user, like `AskUserQuestion`:** `ExitPlanMode`.
  - **Subagents run in the background by default.** Their prompts appear in the lead's pane, even after the lead's `Stop`.
  - **`UserPromptSubmit` also fires for turns Claude starts itself** (a subagent reporting back, a cron, a message from another session). An undocumented `source` field tells them apart.
  - **`SessionEnd` also fires on `/clear` and `/resume`,** while Claude keeps running in the pane.
  - **Teammates:** a split-pane teammate's hooks carry no `agent_id`, and its environment matches the lead's. The team config at `$CLAUDE_CONFIG_DIR/teams/*/config.json` (default `~/.claude/teams/`) lists each teammate's pane as `members[].tmuxPaneId`, with `"leader"` for the lead; that field name is undocumented. `TeammateIdle` fires after a teammate's `Stop`. Teammates in the lead's own pane, the default unless `teammateMode` is `auto` or `tmux`, behave like subagents.
  - **Accepted risks:** detection uses the undocumented `tmuxPaneId` and `source` fields. If they go away, a teammate gets one spurious "done" on its first turn. Two events at the same moment can overwrite each other within a few ms; a lock was rejected because it risked blocking.

## Data model

### Pane state (Design § My calls 1 and 2)
- **Kept as pane options** on the Claude pane, set through `tmux set-option -p -t "$TMUX_PANE"`. The prefix is `@switchboard-`, and the names are the builder's.
- **What's stored:**
  - **role:** lead or teammate
  - **turn state:** working, done or idle
  - **pending prompts:** a compact list of agent keys (`lead`, or a subagent's `agent_id`)
  - **timestamp** of the last change
- **The displayed state is derived:** needs you if any prompt is pending; otherwise the turn state.
- **Teammates never become `done`.** When a lead would become done, a teammate becomes idle (Design § Agent-team teammates).

### Event mapping (as built in A3; S10)

Agent keys are `lead` or the payload's `agent_id`.

| Event | Effect |
|---|---|
| `UserPromptSubmit` | turn → working. A typed prompt (`source` "user" or absent) clears all pending; any other source removes only the lead's key |
| `PermissionRequest`; `PreToolUse` for `AskUserQuestion` or `ExitPlanMode` | add the event's key |
| `Notification`: `permission_prompt`, `elicitation_dialog`, `elicitation_url_dialog` | add the lead's key, only when nothing is pending |
| `PostToolUse`, `PostToolUseFailure` | remove the event's key; the lead's own tool event sets the turn to working |
| `SubagentStop`; `TeammateIdle` or `StopFailure` carrying an `agent_id` | remove that agent's key |
| `Stop`, `StopFailure`, `TeammateIdle` (no `agent_id`) | remove only the lead's key; turn → done, or idle if a client views the session or the pane is a teammate. `TeammateIdle` also marks the pane a teammate |
| `Notification` `idle_prompt` | working → idle |
| `SessionStart` with source startup or resume (a new Claude in the pane) | role detected afresh, turn idle, pending cleared (added in 1.0.1) |
| `SessionStart` with source compact, clear or fork | role kept, or detected when missing; turn → idle only when the pane has none; pending untouched (added in 1.0.1) |
| `SessionEnd` with reason clear or resume | turn idle, pending cleared, role kept |
| `SessionEnd`, any other reason | unset all four options |

**The lead's `Stop` no longer clears subagents' prompts** (a change from the original table): a background subagent's prompt is still on screen after the lead stops.

### Session rows (switcher)
- Each tmux session resolves (S5) to `(repo common dir, worktree root, branch)`, or to "other".
- Its agents are its panes with a role set.
- Its row state is the most urgent agent's, in the order needs you, done, working, idle.

### `@attention` (Design § Status bar, § A slow approved command)
- **Per session,** set as a session option (`set-option -t "=<s>:" @attention …`), so each client's status bar leaves out its own session.
- **Contents:** the attention entries of every **other** session, needs you first, then done, in theme colours. Past a width budget it becomes counts.
- **Rebuilt in one place** (`refresh`) after every state change, every `seen` and on load.

## Command contracts

- **`switchboard`:** the picker.
  - `display-popup -E -w <w> -h <h> -d '#{pane_current_path}' switchboard`, from the dotfiles.
  - It reads the client at start (S4).
  - Rows, keys and preview follow Design § The switcher.
  - Enter on a worktree or agent row runs `switch-client -c <client> -t "=<session>"`, then exits. Esc exits 130.
- **`switchboard hook <event>`:** reads the payload from stdin.
  - Exits 0 at once, silently, when `$TMUX_PANE` is unset or tmux doesn't answer. It never writes to stdout, never blocks, and never exits non-zero.
  - Applies the event mapping, then `refresh`.
  - On a change to needs you, or a lead's change to done, for a session no client is viewing, it alerts: `display-message -c <client>` for each client not on that session, and the sound in the background (Design § My calls 9).
- **`switchboard seen`:** run by tmux's `client-session-changed` hook, with `run-shell -b`. It turns the current session's `done` agents into `idle`, then runs `refresh`.
- **`switchboard refresh`:** rebuilds `@attention` for every session.
- **No tmux server, or not inside tmux:** every command except the picker exits 0 quietly. The picker exits 1 with a message.

## Failure semantics

- **Hook:** any exception is swallowed, and the exit is still 0. The worst case is a stale indicator, never a broken Claude turn.
- **A tmux command failing** in `refresh`, `seen` or the alert is skipped silently.
- **Picker:** a session whose git lookup fails or is slow shows without git status, never blocking the list.

## Stacks and phases

### Stack A: switchboard

- **Base:** `main`
- **Owns:** `src/**`, `tests/**`, `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`, `.github/**`, `contrib/**`, `docs/**`
- **Independent of:** —
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| A1 | Skeleton: package, CLI dispatch, CI, test stubs, LICENSE, README outline; then `gh-harden` with the checks | — |
| A2 | The tmux and git model: sessions → worktrees → repos, panes with state, the project-list labels | A1 |
| A3 | `switchboard hook`: the event mapping, pending prompts, teammates, the fast exit | A2 |
| A4 | `refresh`, `seen` and the alert: per-session `@attention` (A3 layout), alerts and sound | A3 |
| A5 | The picker: rows, keys, folding, search, switching with the pinned client | A4 |
| A6 | The preview and git status in rows | A5 |
| A7 | README, the draft formula, release 1.0.0 | A6 |

- [x] A1: skeleton
- [x] A2: tmux and git model
- [x] A3: hook
- [x] A4: refresh, seen, alert
- [x] A5: picker
- [x] A6: preview and git status
- [x] A7: release 1.0.0

**A1: skeleton**
- **What changes:**
  - `pyproject.toml` (flit, `switchboard = "switchboard.cli:main"`), `src/switchboard/` with `__init__` (version) and `cli.py`. The subcommands `hook`, `seen` and `refresh`, and the bare picker, are stubs that exit as the contracts say.
  - `LICENSE`, MIT with `wmxscott` as the copyright holder.
  - A README outline.
  - `tests/conftest.py`, with stub `tmux` and `fzf` on `PATH` that log their arguments and answer scripted queries, and a temporary `HOME`.
  - A CI workflow copied from pr-tracker's: lint, a test matrix, a smoke test and gitleaks.
- **After merging,** re-run `gh-harden switchboard <CI job names>`.
- **Cites:** S2, S3 and S9.
- *Shippable when:* CI is green on the PR, `switchboard --version` prints the version, and `switchboard hook Stop </dev/null` exits 0 with no output and no `TMUX_PANE`.
- *Split seam:* CI and gh-harden as a follow-up PR.

**A2: tmux and git model**
- **What changes:** modules that read tmux and git without changing anything.
  - One `list-sessions` query, with name, tag, path and last attached.
  - One `list-panes -a` query, with session, window, pane id, current command and the `@switchboard-` options.
  - Resolving the S5 rule with git, including default-branch detection.
  - Reading and labelling `projects.toml`.
  - Building the session rows with the derived state.
- **Cites:** S4–S6, Data model § Session rows.
- *Shippable when:* the tests cover tag and path matching, a `.bare` layout, a normal clone, a non-git session, the default branch first, an invalid or missing `projects.toml`, and urgency ordering.
- *Split seam:* `projects.toml` labelling as A2b.

**A3: hook**
- **What changes:**
  - `switchboard hook <event>` with the full event mapping, pending prompts per agent, and teammates becoming idle instead of done.
  - `SessionEnd` cleanup.
  - The silent fast exit.
- **First,** check S7 against Claude Code's hook docs, and how a teammate is told apart. Record what was found in the PR body, and if anything differs, amend S7 and the mapping in the plan.
- **Cites:** S7, Data model §§ Pane state and Event mapping, Failure semantics.
- *Shippable when:*
  - **Tests cover:** each row of the mapping, parallel subagents not clearing each other, the lead's `Stop` with a subagent still pending, a teammate's `Stop`, `idle_prompt` after an interrupt, and a malformed payload exiting 0.
  - **A timing test** shows a `PostToolUse` with nothing pending stays fast. The builder sets the bar and records the numbers.
- *Split seam:* teammate handling as A3b.

**A4: refresh, seen, alert**
- **What changes:**
  - `refresh` writes per-session `@attention`: names, then counts past the budget, with each client's own session left out.
  - `seen` turns `done` into `idle` for the current session.
  - The alert goes to the right clients, with the sound in the background and `SWITCHBOARD_SOUND`.
  - The hook calls `refresh`, and the alert fires on the right changes.
- **Cites:** Data model § `@attention`, Command contracts, Design §§ Status bar, The alert, My calls 9.
- *Shippable when:* the tests cover names, then counts, your own session left out, no alert for a viewed session, an alert for a lead's done but not a teammate's, `seen` clearing done but not needs-you, and the sound being disabled.

**A5: picker**
- **What changes:**
  - The fzf picker: the three levels, icons, the `▸` for your session, and the "other" group.
  - Search starts disabled. `j`/`k` move, `/` enables search, Tab folds a repo, Enter switches with the pinned client, and Esc closes.
  - Agent rows are dimmed, and Enter on one goes to its session.
- **Cites:** Design § The switcher, S4, Command contracts.
- *Shippable when:*
  - The stub-fzf tests cover each key and the row rendering.
  - A real-tmux popup check on a throwaway server with two clients shows Enter moving the popup's client only. Record it in the PR body.
- *Split seam:* folding and search as A5b.

**A6: preview and git status**
- **What changes:**
  - The preview: name and folder, windows with agent icons, and the last lines of the most urgent agent pane, with trailing blank lines dropped.
  - Git status in worktree rows (`~N ↑M`), gathered without blocking the list (Failure semantics).
- **Cites:** Design § The switcher, Failure semantics.
- *Shippable when:* the tests cover the preview for a session with and without agents, and a slow or failing git lookup leaving the row without status.

**A7: release 1.0.0**
- **What changes:** a complete README, covering what it is, install, the tmux lines for others (the binding, the hook, the refresh on load), commands, the state rules and the documented limitation. Also `contrib/switchboard.rb`, the draft tap formula, and version 1.0.0. After merging, tag `v1.0.0` and create the release `switchboard 1.0.0`.
- *Shippable when:* CI is green and the release exists.

### Stack B: the ai-toolkit plugin

- **Base:** `main`
- **Owns:** —
- **Independent of:** —
- **Depends on:** A (A3's `hook` interface; the merge waits for the 1.0.0 install, R1)

This is a single PR in `wmxscott/ai-toolkit`, so it owns no paths here.

| Phase | Lands | Depends on |
|---|---|---|
| B1 | `plugins/switchboard`: `hooks.json` wiring the S7 events to `switchboard hook <event>`, a README, tests, and marketplace entries, following ai-toolkit's `CLAUDE.md` | A3 |

- [x] B1: ai-toolkit switchboard plugin

**B1 note:**
- The hook command exits 0 silently when `switchboard` isn't on `PATH` or `$TMUX_PANE` is unset.
- Claude Code only; no Codex, Pi or OpenCode wiring.
- Commits go through `git app` (the repo's bot).
- `validate.sh` and pytest must pass.
- After merging, install it on this machine (`claude plugin install switchboard@ai-toolkit`), and add it to the private repo's mise task that installs plugins, which is `shared/claude` on the `main` branch.

### Stack R: rollout

- **Base:** `main`
- **Owns:** —
- **Independent of:** —
- **Depends on:** A, B

| Phase | Lands | Depends on |
|---|---|---|
| R1 | `wmxscott/homebrew-tap`: `Formula/switchboard.rb` at `v1.0.0`; `brew install` on this machine; switchboard added to the dotfiles Brewfile (`stow/brew/.Brewfile`) | A7 |
| R2 | `wmxscott/dotfiles`: `prefix w` opens switchboard in a popup; `client-session-changed` runs `switchboard seen`; the config runs `switchboard refresh` on load; the tmux core design's key table updated | R1, B1 |

- [x] R1: tap formula, install and Brewfile
- [x] R2: dotfiles bindings

**R2 note:**
- The popup's command has no `#{}`, and its folder comes from `-d` (S4).
- `prefix w` replaces `choose-tree -Zs`. `prefix g` keeps tmux's full tree.
- After merging, the user reloads tmux. The tmux files are already stowed, and no new files are added.

## Forest from the trees

### Challenge

The advisor tool isn't available in this session, so here is the strongest case that the sequence is wrong, argued myself.

1. **The user's daily value arrives last.** The picker (A5) and the bindings (R2) come after three phases with nothing to see, and the hook (A3) is useless until B1 and R2 wire it.
   *Response:* kept. The picker's agent rows and the status bar both depend on state existing, and building the picker first on an empty model would force the model into the UI's shape. A2's model is what both consume.
   - **To shorten the dark period,** B1 can be prepared right after A3 and merged at the end, as wkt's R4 was.
   - **A5 is usable by itself** for switching even before any agent state exists.
2. **Hook latency is the riskiest assumption.** Python's startup on every tool call could slow Claude, and it's only measured in A3.
   *Response:* A3's gate includes a timing test with recorded numbers. If it fails, the fallback is a shell fast path in the B1 plugin's command: skip Python when the pane has nothing pending and the event can't change state. That's decided now so A3 doesn't stall.
3. **S7's event facts are unverified.** A wrong assumption about subagent and teammate payloads could invalidate A3.
   *Response:* A3 starts by checking them and must amend the plan before building on different facts.

### Drift test

Ask of every PR:

1. If every phase after this one were cancelled, would the user be closer to never missing an agent that needs them while working in tmux, or is this PR a seam that a later phase in this plan visibly needs?
2. Does any path in this PR need the mouse, poll in a loop, write state files, alert for the session the user is looking at, or risk failing or slowing a Claude turn? It must be no.

## Not doing

- **Selecting an agent or window from the switcher:** deferred (Design § Non-goals).
- **An agents panel, macOS banners, other machines:** out of scope (Design § Non-goals). ~~Agents other than Claude Code~~: now planned in `topsnz-more-agents.md`.
- **Where the project list lives long-term:** deferred to project 4.
- **Screen-scraping panes to detect state:** rejected. It's fragile, and Claude's hooks cover the cases except the accepted limitation.

## Log

- 2026-11-18: plan written from the approved design. The repo was created and hardened (S3).
- 2026-11-18: phase A1 landed as #2. gh-harden now requires `secrets` and the four `test (…)` matrix jobs.
- 2026-11-18: phase A2 landed as #3. The pane options are `@switchboard-role`, `-turn`, `-pending` and `-at` (in `panestate.py`). A pane without its own value inherits a window-level option in formats, so A3 must always use `set-option -p`.
- 2026-11-18: phase A3 landed as #4. Plan amended with S10 and the as-built event mapping: `StopFailure`, `ExitPlanMode`, `TeammateIdle` and team-config detection; subagent prompts survive the lead's `Stop`; `/clear` and `/resume` keep the role. The hook takes about 23 ms per `PostToolUse` on a real tmux, so the shell fast path isn't needed.
- 2026-11-18: phase A4 landed as #5. Alerts fire on changes to the displayed state only (a lead stopping with a prompt pending stays ▲ and doesn't alert "done"). `SessionEnd` always refreshes. For R2, the hook must quote with `#{q:session_name}`.
- 2026-11-18: phase A5 landed as #6. Colours use the 16 ANSI colours (`--color=16`). The pinned client is right when a key on that client opens the popup, which is how the binding works; a popup opened from outside tmux isn't covered, as with wkt. The README's "every command is a stub" line is left for A7.
- 2026-11-18: phase A6 landed as #7. `↑` is left out when origin has no branches. A few hook tests depend on the 2-second `run.TIMEOUT` and could fail under heavy load; harden them if CI does.
- 2026-11-18: phase A7 landed as #8 (switchboard 1.0.0). It needs tmux 3.8 (theme colour names). Known follow-up: a session name starting with `$` makes `=$name` read as a session id, so `refresh` (and the switch) fail for it. wkt's names never start with `$`. Fix by targeting sessions by id in a later release.
- 2026-11-18: phase R1 landed as homebrew-tap#16, with `brew install` done. B1 landed as ai-toolkit#33 (the hook script always exits 0), installed for the user, and added to the private `shared:claude` mise task (dotfiles-private#5). R2 landed as dotfiles#50: `prefix w` (falling back to choose-tree), the `client-session-changed` hook with `#{q:session_name}`, refresh on load, and the Brewfile entry. Every stack has landed.
- 2026-11-18: 1.0.1 shipped (#10): SessionStart is handled, and startup/resume reset the pane. Codex, Pi and per-agent status counts continue in `topsnz-more-agents.md`.
