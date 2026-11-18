# Plan: agent adapters (Codex, Pi) and per-agent status counts

| | |
|---|---|
| **Status** | 1.1.0 released · next: the user's tmux check, then Stack D (sidebar, 1.2.0) |
| **Updated** | 2026-11-18 |
| **Tracker** | — |
| **Related** | [switchboard plan](topih3-switchboard.md) (S10, the event mapping); [design](../superpowers/specs/2026-11-18-switchboard-design.md) |

## Goal

switchboard tracks Codex and Pi agents alongside Claude Code. Each agent's event handling lives in its own adapter module under `src/switchboard/agents/`, so contributors can add more agents. The status bar shows how many agents in a worktree need you or are done.

**Falsifiable:** after this plan:
- A Pi session in tmux shows in the picker as `pi · win N`, and its run ending alerts ✓.
- A Codex session started with `codex --no-daemon` shows as `codex · win N`.
- A worktree with two agents needing you reads `▲² name` in the status bar.
- Adding an agent means one new `agents/<name>.py` with its tests, and nothing else in switchboard.

### Done when

- [x] switchboard 1.1.0 is released through the tap, with CI green.
- [x] The README has an "Adding an agent" guide.
- [x] The ai-toolkit Pi extension and Codex hooks are merged and installed on this machine.
- [ ] In the user's tmux:
  - a Pi session shows and alerts ✓ when its run ends
  - a worktree with two agents needing you shows `▲²`
  - a daemon-mode `codex` session is ignored, not shown in the wrong pane

## Settled: do not re-derive

- **S1 The research is done.** Codex and Pi were each researched on 2026-11-18. The full notes went to the session scratchpad (`agents-research/codex.md`, `agents-research/pi.md`), and this plan carries every fact it needs.
- **S2 Every agent gets an adapter module (user's decision).** Each agent's event handling lives in its own module, `src/switchboard/agents/<name>.py`, so new agents are easy to add and outsiders can contribute.
  - **Registry:** `agents/__init__.py` maps a name to its module, and an unknown name is a silent no-op.
  - **Shape:** an adapter turns `(event, payload)` into calls on the shared core (S4). It never talks to tmux itself.
  - **Rejected:**
    - Mapping in each integration, for example the Pi extension sending only core verbs. That splits logic across repos and languages, and outsiders couldn't contribute a mapping here.
    - One big `hook.py`, which is today's shape.
- **S3 The CLI.**
  - **`switchboard hook [--agent NAME] <Event>`:** the payload is JSON on stdin, and `--agent` defaults to `claude`. Any other value selects `agents/<NAME>` and turns on the pane guard (S6).
  - **`switchboard state <start|working|done|idle|needs KEY|resolve KEY|all|end> [--agent NAME]`:** the generic core verbs, with no stdin, for scripts and tools that have no adapter.
  - **The contract, the same as today's hook:**
    - it never prints;
    - a runtime problem always exits 0;
    - malformed arguments to `state` exit 2 with one line on stderr;
    - a fast path runs before argparse.
- **S4 The core verbs** (`src/switchboard/core.py`) work on one pane's stored state. Each reads once, writes once and only on a change, then runs `changed()` (the alert, then refresh).
  - **`start`:** a new agent process. Detect the role, set the turn to idle, clear pending prompts and set the label.
  - **`working`:** set the turn to working.
  - **`done`:** set the turn to done, or to idle when a client views the session or the pane is a teammate.
  - **`idle`:** set the turn to idle.
  - **`needs KEY` / `resolve KEY|all`:** change pending prompts only.
  - **`end`:** unset every `@switchboard-*` option.

  An adapter may combine verbs, for example `done` plus `resolve lead`, in a single write. Claude's existing behaviour (S10 of the switchboard plan) must come out unchanged from `agents/claude.py` on this core. The alert rules (displayed-state changes) are unchanged.
- **S5 Label:** a new pane option, `@switchboard-agent`, added to `panestate.OPTIONS` and `Pane.agent`.
  - Every write sets it: `claude` by default, or the `--agent` name. That fixes a stale label left by a crashed agent of another kind.
  - The picker shows `teammate` for teammates, otherwise the label, otherwise `claude`.
- **S6 The pane guard (Codex daemon mode).**
  - **The problem:** since 0.157, Codex runs sessions in a shared daemon whose environment is that of the first TUI that started it, so `$TMUX_PANE` is wrong.
  - **The user decided (2026-11-18): no `--no-daemon` wrapper.** switchboard must ignore Codex sessions it can't place. It tracks only embedded ones, started with `codex --no-daemon`.
  - **The fix:** add `#{pane_pid}` to the read. Before any write for a non-Claude agent, check that `pane_pid` is an ancestor of the hook process, with one `ps -axo pid=,ppid=` call (about 17 ms, only on writes). If it isn't, drop the event silently.
  - **Claude is unaffected.**
- **S7 Status counts (user's decision, superscripts).**
  - **One entry per worktree,** in its most urgent group. Each state that's present gets an icon, with a superscript count only when more than one agent is in that state: `▲ name`, `▲³ name`, `▲²✓ name`, `✓² name`.
  - **What's counted:** agents (panes) in that displayed state. Subagent prompts don't count separately.
  - **Unchanged:** the counts mode for a crowded bar (`▲ 4 need you…`), which counts worktrees.
- **S8 Codex facts** (Codex 0.170.0; docs plus source at `rust-v0.170.0`).
  - **Hooks:** they're in Claude's format: Claude's event names, a Claude-shaped JSON payload on stdin, and `CLAUDE_PLUGIN_ROOT` set.
  - **Events:** PreToolUse, PermissionRequest, PostToolUse, PreCompact/PostCompact, SessionStart (startup|resume|clear|compact|fork), SessionEnd (reason always "other"), UserPromptSubmit, SubagentStart/Stop, Stop, **Interrupt**, Pre/PostModelRequest.
  - **Missing events:** Notification, PostToolUseFailure, StopFailure and TeammateIdle. `request_user_input` (through PreToolUse) is Codex's version of AskUserQuestion.
  - **Payloads:**
    - A subagent's UserPromptSubmit carries `agent_id`. It means the subagent got its task, not that you typed something.
    - Stop and Interrupt have no `agent_id`.
    - UserPromptSubmit has no `source`.
  - **Gaps:**
    - A failed turn fires neither Stop nor Interrupt.
    - PermissionRequest fires before the auto-reviewer decides, so ▲ can flash briefly.
    - MCP elicitations have no hook.
  - **Delivery:** hooks run `$SHELL -lc`. Stdout reaches the model on SessionStart and UserPromptSubmit. SessionEnd and Interrupt timeouts are capped at 3 s. Hooks must be trusted in `/hooks`.
- **S9 Pi facts** (Pi 1.5.2's `docs/extensions.md`, plus a sandboxed RPC probe).
  - **Events:**
    - `session_start {reason}` and `session_shutdown {reason: quit|reload|new|resume|fork}`.
    - `agent_start`, which repeats on retries.
    - `agent_settled {aborted}`: final, and the docs say to use it for status.
    - `ui_prompt_start {kind, title}` / `ui_prompt_end`: they wrap every extension dialog, and nested dialogs coalesce into one span.
    - `pi.events` `plannotator:session-opened` / `-closed` `{id, action}`.
  - **No built-in permission prompts**, and built-in waits (the trust prompt, `/login`) send no event.
  - **`ctx.ui.custom()`** fires `ui_prompt_start` even for UI that doesn't block, so a false ▲ is accepted.
  - **When to act:** only when `ctx.mode === "tui"`, `TMUX_PANE` is set and the CLI is found. RPC mode reports `hasUI`, and subagent children inherit `TMUX_PANE`.
  - **Calling the CLI:** handlers are awaited, so spawn the CLI detached with `stdio:"ignore"` and `unref`, and never await it except on quit. Serialize calls through a process-global queue, and never touch `pi` or `ctx` in a callback.
  - **Version:** Pi 1.1.0 or newer.
- **S10 The Pi payload contract.** The ai-toolkit extension calls `switchboard hook --agent pi <event>`, with `{"event": "<event>", ...fields}` on stdin. `agents/pi.py` maps these:

  | Event | Fields | Effect |
  |---|---|---|
  | `session_start` | `reason`, `idle` (bool) | `start`, then `working` if not idle |
  | `agent_start` | — | `working` |
  | `ui_prompt_start` / `ui_prompt_end` | `kind` | `needs ui` / `resolve ui` |
  | `plannotator_opened` / `plannotator_closed` | `id` | `needs <id>` / `resolve <id>` |
  | `agent_settled` | `aborted` | `done` (`resolve all`), or `idle` when aborted |
  | `session_shutdown` | `reason` | `end` when `quit`; otherwise nothing |
- **S11 The Codex mapping (`agents/codex.py`):** the Claude mapping, with these changes:
  - `Interrupt` resolves the lead's key and turns working into idle, with no alert.
  - `PreToolUse` with `request_user_input` adds a pending key.
  - `UserPromptSubmit` with an `agent_id` resolves only that key and doesn't touch the turn.
  - `SessionEnd` always ends.
  - It reuses `agents/claude.py` rather than copying it.

- **S12 The sidebar (user's decisions, 2026-11-18).**
  - **The toggle:** `prefix b` (a bare `Ctrl-W` would steal the shell's and Neovim's keys) opens a ~32-column pane on the left of the current window, or closes it if it's there. The pane is tagged with a pane option, for example `@switchboard-sidebar`, and opens without taking focus (`split-window -hbd`).
  - **It stays in that window.** It doesn't follow you into other sessions. *(Rejected: one that follows you, which would add panes to windows you didn't touch and squeeze their layouts.)*
  - **What it shows:** the picker's list in compact form: repo headers, and worktree rows with their state dot. Agents fold into the dot, your session is highlighted, and there's no preview. It uses the same keys and look as the picker, and Enter switches session while the sidebar stays.
  - **Live updates:** it redraws when state changes. `refresh` pokes each sidebar's fzf `--listen` socket with a reload. No polling.
  - **Restore:** tmux-resurrect restores it as a sidebar, via `@resurrect-processes`, not as a stray shell.
  - **Version:** it ships in 1.2.0, after 1.1.0 (Codex and Pi), and builds on the picker-look branch.

## Stacks and phases

### Stack S: switchboard core and adapters

- **Base:** `main`
- **Owns:** `src/switchboard/core.py`, `src/switchboard/agents/**`, `src/switchboard/hook.py`, `src/switchboard/cli.py`, `src/switchboard/panestate.py`, `src/switchboard/tmux.py`, `src/switchboard/picker.py`, `src/switchboard/preview.py`, `tests/test_hook.py`, `tests/test_cli.py`, `tests/test_tmux.py`, `tests/test_picker.py`, `tests/test_preview.py`, `tests/test_core.py`, `tests/agents/**`, `README.md`, `src/switchboard/__init__.py`, `contrib/**`, `docs/**`
- **Independent of:** C (it owns attention rendering only), X and P (other repo)
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| S1 | Refactor: `core.py` with the verbs, and `agents/` with the registry and `claude.py`, with no behaviour change. Also `hook --agent`, `state`, the label and the pane guard | — |
| S2 | `agents/codex.py` and `agents/pi.py`, with tests | S1 |
| S3 | README (the "Adding an agent" guide, Codex and Pi setup, counts) and release 1.1.0 | S2, C1 |

- [x] S1: core, agents package, label, state, guard
- [x] S2: Codex and Pi adapters
- [x] S3: README and 1.1.0

**S1** (S2–S6):
- **What changes:**
  - Move today's `hook.py` mapping into `agents/claude.py` over `core.py`. `hook.py` becomes the dispatcher.
  - Add `state`, the `@switchboard-agent` label (`Pane.agent`, picker label), and the guard.
- *Shippable when:*
  - every existing hook test passes unchanged in behaviour (tests may move);
  - new tests cover each `state` verb, the registry's unknown-agent no-op, the label written and shown, and the guard both passing and dropping;
  - the timing test still passes.
- *Split seam:* the pure refactor as S1a, then `state`, label and guard as S1b.

**S2** (S8–S11):
- **What changes:** the two adapter modules and their tests in `tests/agents/`.
- *Shippable when:* every row of S10 and S11 is tested; a Codex subagent `UserPromptSubmit` doesn't clear the lead's prompts; `Interrupt` with a pending prompt goes to idle with no alert; and daemon-mode Codex (pane not an ancestor) is dropped.

**S3:**
- **What changes:**
  - **README:** an "Adding an agent" section (the adapter interface, the registry, tests, `state` for tools with no adapter); Codex setup, including the daemon caveat and `--no-daemon`; Pi setup; and the counts.
  - **Release:** version 1.1.0, the formula, the tag and the release.
- *Shippable when:* CI is green and the release exists.

### Stack C: status counts

- **Base:** `main`
- **Owns:** `src/switchboard/attention.py`, `tests/test_attention.py`
- **Independent of:** S, X, P
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| C1 | Superscript per-agent counts in `@attention` (S7) | — |

- [x] C1: status counts

**C1:**
- *Shippable when:* the tests cover a single agent (unchanged), `▲³`, `▲²✓`, `✓²`, sessions sitting in the needs group, colours per icon, the budget measured with the counts included, and counts mode unchanged.

### Stack X: ai-toolkit Codex hooks

- **Base:** `main` (ai-toolkit)
- **Owns:** —
- **Independent of:** C
- **Depends on:** S (`hook --agent codex` in 1.1.0; it can be built before, against a stub)

A single PR in `wmxscott/ai-toolkit` (S8):
- `plugins/switchboard/.codex-plugin/plugin.json` with `"hooks": "./hooks/codex.json"`
- `hooks/codex.json`: SessionStart, UserPromptSubmit, PreToolUse (`request_user_input`), PermissionRequest, PostToolUse, Stop, SubagentStop, Interrupt and SessionEnd. Each runs `hook.sh <Event> codex`, with a timeout of 5, or 3 for SessionEnd and Interrupt.
- `hook.sh` passes `--agent`, and skips Codex when `CLAUDECODE` is set.
- An `.agents/plugins/marketplace.json` entry, a root README tick, a plugin README section (trust in `/hooks`, the daemon caveat), tests, and a `CLAUDE.md` note.

It merges after 1.1.0 is in the tap. Then add `codex plugin add switchboard@ai-toolkit` to the private `shared:codex` mise task.

- [x] X1: Codex hooks

### Stack P: ai-toolkit Pi extension

- **Base:** `main` (ai-toolkit)
- **Owns:** —
- **Independent of:** C
- **Depends on:** S (`hook --agent pi` in 1.1.0; it can be built before, against a stub)

A single PR in `wmxscott/ai-toolkit` (S9, S10):
- `pi/extensions/switchboard.ts`: a thin forwarder that sends the S10 events to `switchboard hook --agent pi <event>`. It uses the TUI, `TMUX_PANE` and CLI gate; a process-global serialized queue; a detached, never-awaited spawn; and a 1 s drain on quit.
- The `package.json` `pi.extensions` entry, a root README row and a `pi/README.md` section.
- Tests in `tests/test_pi.py`: a harness with a fake API and a stub CLI, plus a real-Pi run in RPC mode with `fauxProvider` and a widened-modes copy.

It merges after 1.1.0 is in the tap.

**Note on X and P:** they're built in parallel but both touch ai-toolkit's root `README.md`, so they're not strictly independent. Whichever lands second merges `main` and resolves the README rows.

- [x] P1: Pi extension

### Stack D: sidebar (1.2.0)

- **Base:** `main`
- **Owns:** `src/switchboard/sidebar.py`, `tests/test_sidebar.py`
- **Independent of:** X, P
- **Depends on:** S (1.1.0 released), and the picker-look branch merged

| Phase | Lands | Depends on |
|---|---|---|
| D1 | `switchboard sidebar`: the compact list, live reload through fzf `--listen`, Enter switches and the sidebar stays | S3 |
| D2 | `switchboard sidebar --toggle`, the pane tag, the README, release 1.2.0 | D1 |
| D3 | dotfiles: `bind b` and `@resurrect-processes` for the sidebar | D2 |

- [ ] D1: sidebar list
- [ ] D2: toggle and 1.2.0
- [ ] D3: dotfiles binding

## Forest from the trees

### Challenge
The advisor isn't available, so here's my own case against the plan.

1. **S1 is a refactor of a working system under the user's live sessions.**
   *Response:* S1 must pass every existing hook test unchanged in behaviour. The release (S3) comes after the adapters, so main may hold the refactor before release.
2. **Putting Pi's mapping in switchboard couples releases to Pi's API churn.** The Pi research argued for verbs in the extension instead.
   *Response:* the user chose extensible in-repo adapters (S2). The thin forwarder keeps Pi-specific gating in the extension, and a Pi rename means an adapter change and a patch release. Accepted.
3. **Codex value is limited by the daemon decision.**
   *Response:* the guard makes it correct rather than wrong, and the README tells the user how to opt in. Accepted: Codex use is rare.

### Drift test
1. If every phase after this one were cancelled, would switchboard be more able to track an agent other than Claude, or show the counts? Or is this PR a seam a later phase visibly needs?
2. Does this PR change Claude's tracking behaviour, write to a pane not proven to be the agent's own, or make the hook print or fail? It must be no.

## Not doing

- **A `--no-daemon` wrapper for Codex:** rejected by the user.
- **Pi's built-in waits** (trust, `/login`): out of scope, since they send no event.
- **Reading OSC 7501:** rejected, since tmux doesn't forward it.
- **Integration code in switchboard's repo** (the Pi extension, Codex hooks files): it ships through ai-toolkit. The README documents the wiring for others.

## Log

- 2026-11-18: plan written from the Codex and Pi research and the user's decisions: superscripts, no Codex wrapper, adapters in `agents/`.
- 2026-11-18: C1 landed as #12, S1a as #13 and S1b as #14. X1 is ai-toolkit#35 and P1 is ai-toolkit#36, both open and waiting for 1.1.0. Plan amended with S12 and Stack D, the sidebar the user asked for (stays in its window, `prefix b`).
- 2026-11-18: S2 landed as #16. S3 (README and the 1.1.0 bump) opened; the tag waits for the picker look pass so 1.1.0 carries both.
- 2026-11-18: S3 landed as #17, and the picker look pass (shared with wkt 2.3.0) as #18. Released 1.1.0 (tap#18; wkt 2.3.0 is tap#19). X1 landed as ai-toolkit#35 and P1 as #36, installed here; the private `shared:codex` task installs the plugin (dotfiles-private#6).
