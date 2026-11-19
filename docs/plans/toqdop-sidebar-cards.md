# Plan: agent cards in the sidebar (1.4.0)

| | |
|---|---|
| **Status** | draft · next: A1, once 1.3.0 has landed |
| **Updated** | 2026-11-18 |
| **Tracker** | — |
| **Related** | [design, approved 2026-11-18](../superpowers/specs/2026-11-18-sidebar-cards-design.md); [previous plan](topsnz-more-agents.md) (S12 and Stack D, the sidebar) |

## Goal

While a window has switchboard's sidebar open, agents that need you or have finished show as cards at the bottom of that sidebar. Each card says which agent and why. You pick one with the sidebar's keys to land on that agent's pane, and the cards stand in for the status bar's ▲✓ segment.

**Falsifiable:** after this plan, with a sidebar open in the window you're looking at, and an agent in another session asking to run `npm test`:
- a card `▲ <session> · claude` / `  run: npm test` is the bottom item of the sidebar;
- `G` then Enter lands on that agent's pane;
- the card goes away once you've answered;
- your status bar shows no ▲ while the sidebar is open.

### Done when

- [ ] switchboard 1.4.0 is released through the tap with CI green, and installed here.
- [ ] The README documents the cards, `G`/`g`, the "why" per agent, and the hidden segment.
- [ ] In the user's tmux, on a real Claude session:
  - a permission prompt in another session shows its card with the command;
  - `G` and Enter land on the agent's pane;
  - the card goes on approval, or when the command ends;
  - a finished turn shows `✓ … done: <prompt>` until you visit;
  - the status bar has no segment while the sidebar is open, and has it back when it's closed.
- [ ] The ai-toolkit Pi extension sends `title` and forwards `input`, so Pi cards show their reason.

## Settled: do not re-derive

- **S1 The design is approved** (2026-11-18). The spec linked above is the record of the user's decisions. This plan is the live artifact, and it carries every decision it needs.
- **S2 Which cards (user):**
  - one card per agent that needs you (▲) or is done (✓); idle and working agents get none;
  - teammates get needs-you cards (they never reach done);
  - no cards for the sidebar's own session, the same rule as the status bar, which never lists your own session (my call, see S4).
- **S3 What a card says (user):** line 1 is the agent, as its session and its label; line 2 is why it needs you, or what it finished. The contract is in [Card content](#card-content).
- **S4 A card follows the agent's state (user):** it goes when you've answered (needs you) or visited (done), and is never dismissed by hand.
  - **Known and accepted for the status bar since 1.0:**
    - a slow approved command keeps "needs you" until it ends, because Claude Code sends no event between the approval and the tool's end;
    - a rejected or interrupted prompt keeps it until the next typed prompt.
  - Cards inherit both. That's why the sidebar's own session gets no cards (S2).
  - **Rejected:** hiding a card while its agent's pane is visible. That needs window-change hooks and client tracking, against "no polling" and "no config change".
- **S5 The look is style "A" (user):**
  - plain, two lines per card, under a rule;
  - the newest at the bottom, with older ones pushed up;
  - one card is one fzf item, and the cursor never stops on a card's second line.

  **Rejected:**
  - boxed toast-style cards ("B"), the user's choice;
  - fzf's footer, which can't be selected;
  - a second fzf pane for the cards, which breaks moving from the list to the cards with `j`.
- **S6 Cards are always visible (my call, from the builder check):** when the list is taller than the pane, the list scrolls and the stack stays at the bottom. Past what fits, the oldest cards fold into one `+N more` line, and Enter on it does nothing.
  - **Rejected:** cards that scroll off below a long list, which defeats them.
- **S7 Keys (user):**
  - `G` jumps to the newest card, and `g` to the top of the list;
  - the cursor never moves by itself, neither when a card arrives nor when you move into the sidebar.

  **Rejected:**
  - Ctrl-D and Ctrl-U, because Ctrl-D deletes a worktree in wkt's picker, which shares the look and keys;
  - jumping to the newest card on pane focus.
- **S8 The status bar and the alert:**
  - **The segment (user):** a client whose current window has a sidebar shows no ▲✓ segment, and no `prefix w` hint either (my call: the whole segment hides).
  - **The message (my call):** the alert's tmux message skips those clients.
  - **The sound** always plays.
- **S9 Pi reports through `switchboard hook --agent pi <event>` JSON** (fact: `ai-toolkit/pi/extensions/switchboard.ts`).
  - Its reasons come through `agents/pi.py`:
    - `title` on `ui_prompt_start` (the extension sends only `kind` today);
    - a new `input` event, for the prompt line.
  - The extension change is Stack P, in ai-toolkit.
  - Either order is safe: an older switchboard ignores unknown fields and events, and a newer one without them draws a plain card.
  - `switchboard state` gains `--reason` and `--task` only for tools without an adapter.
- **S10 This builds on 1.3.0** (branch `feat/jump-to-agent`):
  - picking lands on the agent's pane with `switch-client -t %PANE`, falling back to `=SESSION` if the pane has gone;
  - sidebar items become `session\tpane\tgroup\tdisplay`.

  Fact, checked on tmux 3.8 (2026-11-18): `switch-client -t %PANE` selects that pane's session, window and pane in one command.
- **S11 fzf facts:**
  - `--read0` with items that span lines is supported from 0.53 (the floor is 0.59);
  - `--id-nth`, which keeps the cursor on an item across reloads, needs 0.71, so the redraw works out `pos()` itself;
  - `--layout=default` draws items from the bottom up, and `reverse` from the top down (fzf 0.75 man page).

  Whether 0.59 draws multi-line items the same way is **not verified**, and A3 checks it.
- **S12 The hook stays fast:**
  - reasons are read from fields already parsed, with no new imports on the fast path;
  - a missing or renamed payload field gives a plain card (`needs you`, `done`) and never an error.
- **S13 A "why" can hold a secret** (a token in a command line). It's stored in a pane option, which only the user's own tmux server can read, and drawn on their own screen, where the agent's prompt already shows it. That's accepted, with a README line.
- **S14 Release** is as before: tag `v1.4.0`, then the tap formula from `contrib/switchboard.rb`, then `brew upgrade`. There's no release in between phases.
- **S15 One switchboard stack, not three.** A split was considered:
  - F: the storage seam;
  - R: the adapters;
  - K: the cards, with R and K both on F.

  **Rejected:** R is one PR. Running it beside K saves one review cycle, but costs a second base and a release phase that depends on both.

## Card content

### Lines

- **Line 1:** the mark (red ▲ for needs you, green ✓ for done), then the session name, then `· ` and the agent's label (`claude`, `codex`, `pi`, or the teammate's name). It's cut to the pane width with `…`. When one agent has several prompts pending, the mark carries a superscript count (`▲²`), as in the status bar.
- **Line 2:** two spaces, then the "why", cut with `…`.

### The "why" per agent and event

| Agent and event | Line 2 |
|---|---|
| Claude `PermissionRequest`, Bash | `run: <command>` |
| Claude `PermissionRequest`, a tool with a `file_path` | `<verb>: <path>`, e.g. `edit: src/app.py` |
| Claude `PermissionRequest`, any other tool | the tool's name |
| Claude `PreToolUse` `AskUserQuestion` | `asks: <first question>` |
| Claude `PreToolUse` `ExitPlanMode` | `plan ready for review` |
| Claude `Notification` (`permission_prompt`, `elicitation_*`) | its `message` |
| Codex `PermissionRequest` (Claude-shaped payload) | as Claude |
| Codex `PreToolUse` `request_user_input` | `asks: <first question>` |
| Pi `ui_prompt_start` | `title`, else `kind` |
| Pi Plannotator opened | `plan ready for review` |
| Done, any agent | `done: <first line of the turn's prompt>`, else `done` |
| Needs you, no reason known | `needs you` |

- **Where the prompt line comes from:** Claude's and Codex's `UserPromptSubmit` `prompt`, and Pi's `input` event.
- **Several pending prompts:** line 2 is the most recent prompt's reason.
- **The wording per tool** is the builder's call, within the table's spirit: short, and the thing you'd answer.

### Stored form

- Every reason and prompt line is stored as one line: control characters and newlines stripped, nothing tmux treats specially left in, and capped at 200 characters when it's stored.
- Cutting to the pane width happens only when the card is drawn.

## State storage

### New pane options

- **A reason for each pending key**, so that resolving one key leaves the others' reasons intact.
- **The current turn's prompt line**, called the task.
- **A time for each card**, used to order the stack:
  - needs you: when its latest prompt arrived;
  - done: when the turn ended.

  If `@switchboard-at` already changes on exactly those moves, reuse it. Otherwise add one.
- Names and encoding are the builder's call. They must be tmux-safe like `encode_pending`, parse in the same single `list-panes` read as today's options (`tmux.PANE_FIELDS`), and be listed in `panestate.OPTIONS` so `end` clears them.

### Verb contract (`core.py`)

| Verb | Reasons | Task |
|---|---|---|
| `needs(key, reason="")` | sets that key's reason, or the plain default | — |
| `resolve(key)` | drops that key's reason | — |
| `RESOLVE_ALL` | drops all | — |
| `working(task="")` | — | sets it, if given |
| `DONE` / `IDLE` | — | kept, so a done card can show it |
| `START` | drops all | dropped |
| `END` | all options unset (as today) | dropped |

- Writes still happen once, and only on a change, as today.

### The `state` command

- **New flags:** `switchboard state needs KEY [--reason TEXT]` and `switchboard state working [--task TEXT]`. Final names are the builder's call.
- Malformed arguments still exit 2, and today's calls are unchanged.

## The sidebar

### Items

- Every sidebar item is NUL-separated (`--read0`), and one card is one item across two lines.
- Every consumer of the item text keeps working:
  - `{1}`/`{2}` in `__switch`, the folds and `pos()`;
  - the current-session marker;
  - search;
  - the poke's reload.
- A card item carries the agent's pane, so Enter uses 1.3.0's pane jump with its session fallback (S10).

### Layout

- **From the top:** the list; then an empty gap; then a rule and the cards, oldest first and newest last. The stack is always drawn whole (S6).
- **With no cards:** no rule and no gap item drawn as content, and the list still starts on the top row.
- **One lead:** `--layout=default` draws from the bottom up. Feed the items in reverse, so the cards are first in the input and stay on screen, while the list scrolls off the top when it's long. Then size a single blank gap item to the pane's height.
- The gap is never a cursor stop. `j` from the last list row goes to the first card, and `k` comes back.
- How the gap is drawn and skipped is the builder's call.
- **When crowded:** the list keeps at least 3 rows, and cards that don't fit in the rest fold into `+N more`, the oldest first. Enter on `+N more` does nothing.
- **Search** (`/`) matches cards as well as list rows. The gap and the rule never match.

### Keys and cursor

- **`G`** jumps to the newest card, or to the last list row when there are no cards. **`g`** jumps to the first list row.
- Both are bound like `j`/`k`: unbound while searching, and bound again when the search ends.
- **Across redraws**, the cursor stays on the same item, by identity rather than by row number. If its card has gone, the cursor goes to the nearest card, or to the list when there are none. Enter never acts on a different agent than the one the cursor was on. With the fzf 0.59 floor (S11), the poke sends a `transform` that works out `pos()`.

## The status bar and the alert

### The segment

- A client whose current window has a sidebar pane shows no segment at all (S8). Every other client and window is unchanged.
- **One lead:** switchboard wraps the `@attention` value it writes in `#{?#{P:#{@switchboard-sidebar}},,…}`, which needs no change to anyone's tmux config. Verify it through `#{E:@attention}` on tmux 3.8.

### The alert

- The sound plays for every alert, as today.
- `display-message` goes only to clients whose current window has no sidebar pane.

## Failure semantics

- **A missing payload field** gives the plain reason. The hook never fails over a reason (S12).
- **A pane gone at pick time** falls back to the session, as in 1.3.0.
- **A sidebar that isn't listening** (still `starting`, or its fzf died) misses the poke, as today. The next state change redraws it.
- **Restored sidebars** (tmux-resurrect) hold no saved layout. That changes nothing here: cards come from the live pane state.

## Stacks and phases

### Stack A: switchboard

- **Base:** `main`
- **Owns:** `src/switchboard/**`, `tests/**`, `README.md`, `contrib/switchboard.rb`, `docs/plans/toqdop-sidebar-cards.md`
- **Independent of:** P (an older switchboard ignores the new Pi field and event, and the new one copes without them)
- **Depends on:** —

| Phase | Lands | Depends on |
|---|---|---|
| A1 | reasons and the task stored in the pane state, and the `state` flags | — |
| A2 | each adapter gives its reasons and prompt line | A1 |
| A3 | sidebar items become NUL-separated and draw bottom-up, and look exactly as today | A2 |
| A4 | the cards: model, stack, rule, `+N more`, Enter to the pane | A3 |
| A5 | `G`/`g`, and the cursor keeps its item across redraws | A4 |
| A6 | the segment hides and the message skips when a sidebar is open | A5 |
| A7 | README and 1.4.0 | A6 |

- [ ] A1: reasons in the state
- [ ] A2: adapters give reasons
- [ ] A3: NUL-separated, bottom-up sidebar
- [ ] A4: the cards
- [ ] A5: `G`/`g` and a steady cursor
- [ ] A6: the sidebar stands in for the segment and message
- [ ] A7: README and 1.4.0

**A1: reasons in the state.**
- The new pane options and their parsing in `tmux.PANE_FIELDS`/`Pane`.
- The verb contract in [State storage](#state-storage), and the sanitiser and cap from [Stored form](#stored-form).
- `state needs KEY --reason`, and `working --task`.
- No adapter sets a reason yet, and nothing draws one.
- Cites S9, S12 and State storage.

*Shippable when:* tests and lint pass; `switchboard state needs x --reason 'run: ls'` on a throwaway tmux server leaves the reason in the pane option, and `resolve x` removes it.
*Split seam:* the `state` CLI flags after the core storage.

**A2: adapters give reasons.**
- `agents/claude.py`, `codex.py` and `pi.py` map each event to its reason and prompt line, as in the [table](#the-why-per-agent-and-event): `pi.py` reads `title` and a new `input` event.
- Payload fixtures in the tests for each row.
- Claude's `UserPromptSubmit` `prompt` becomes the task.
- The README's "Adding an agent" says how an adapter gives reasons.
- Cites S9, S12 and Card content.

*Shippable when:* tests and lint pass; a recorded Claude `PermissionRequest` payload piped to `switchboard hook PermissionRequest` in a throwaway tmux pane stores `run: <command>`.
*Split seam:* `pi.py` after Claude and Codex.

**A3: NUL-separated, bottom-up sidebar.**
- The sidebar's fzf moves to `--read0`.
- The layout draws so a stack at the bottom will always stay on screen (see [Layout](#layout)), with the gap mechanism and its cursor skipping, but no cards yet.
- The list looks and behaves exactly as in 1.3.0: folds, search, Enter, redraw, the current-session marker, and the list on the top row.
- Check it on fzf 0.59 as well as 0.75 (S11). A 0.59 binary from fzf's GitHub releases, run only inside the throwaway server, is enough.
- If 0.59 can't do it, stop and report: raising the floor is the user's decision.
- Cites S5, S6, S11 and Items and Layout.

*Shippable when:* tests and lint pass; on a throwaway tmux server with fzf 0.59 and 0.75, a sidebar with 2 repos and a folded group looks exactly as 1.3.0's, row for row, and `j`/`k`, Tab, `/`, Esc and Enter work as before.
*Split seam:* the `--read0` item format first, then the bottom-up layout and the gap.

**A4: the cards.**
- A card model: a pure function from the panes and the sidebar's session to the ordered cards, applying S2 and S6's fold.
- The stack, the rule and `+N more` in the sidebar.
- Enter on a card goes to its pane.
- Redrawn on the existing poke.
- Cites S2–S6, S10, Card content and Layout.

*Shippable when:* tests and lint pass; on a throwaway server, `switchboard state needs k --reason 'run: npm test'` in another session's pane makes the card the sidebar's bottom item; Enter on it lands on that pane; `resolve k` removes it.
*Split seam:* the card model, with its tests, first.

**A5: `G`/`g` and a steady cursor.**
- The keys and the redraw `transform`, as in [Keys and cursor](#keys-and-cursor).
- Cites S7 and S11.

*Shippable when:* tests and lint pass; on a throwaway server, with the cursor on a card, a new card arriving leaves the cursor on the same card; the cursor's card resolving moves it to the nearest card; `G` and `g` reach both ends; `/` disables them and Esc brings them back.
*Split seam:* `G`/`g` first, then the steady cursor.

**A6: the sidebar stands in for the segment and the message.**
- `attention.py`'s segment and `alert.py`'s message, as in [The status bar and the alert](#the-status-bar-and-the-alert).
- Cites S8.

*Shippable when:* tests and lint pass; on a throwaway server with two clients, the one whose window has a sidebar shows no segment and gets no message on an alert, and the other shows both.
*Split seam:* the segment, then the message.

**A7: README and 1.4.0.**
- README:
  - the sidebar section gains the cards, a mockup like the one in the spec, `G`/`g`, and the "why" table;
  - the status bar section says the segment hides;
  - a line on S13.
- `__version__` 1.4.0, and the formula url.
- The plan's Log.

*Shippable when:* tests and lint pass, and the README's commands and keys match the code.
*Split seam:* none needed; this is docs and a version bump.

### Stack P: ai-toolkit Pi extension

- **Base:** `main`
- **Owns:** `pi/**`
- **Independent of:** A (S9)
- **Depends on:** —

This stack is in the `wmxscott/ai-toolkit` repository. `Owns` is relative to that repo, so `stack_overlap.py` run in switchboard never sees it.

| Phase | Lands | Depends on |
|---|---|---|
| P1 | the extension sends `title` on `ui_prompt_start` and forwards `input` with its prompt text | — |

- [ ] P1: Pi sends reasons

**P1: Pi sends reasons.**
- `pi/extensions/switchboard.ts` adds `title` to the `ui_prompt_start` payload, and sends an `input` event with the prompt's first line.
- It stays fire-and-forget, as today.
- Update `tests/test_pi.py` and the Pi README.
- Commit with `git app` and `gh app-auth exec`.

*Shippable when:* ai-toolkit tests pass; with switchboard 1.4.0, a Pi dialog in tmux shows its title on the card.
*Split seam:* none needed.

## Forest from the trees

### Challenge

There's no advisor tool in this session, so here is the strongest case against the sequence, argued myself.

- **The case:** A3 is a risky refactor (`--read0`, a bottom-up layout, a gap item) that delivers nothing visible. A4 might find the bottom-up approach wrong for cards and redo it. Meanwhile A1 and A2 store reasons that nothing shows until A4. Three phases land with no user-visible change, and if A3's approach fails on fzf 0.59, A1 and A2 sit unused.
- **What it surfaced:**
  1. A3's risk is real. Its *Shippable when* now requires fzf 0.59 as well as 0.75, and a stop-and-report if 0.59 can't do it. That turns the riskiest unknown into the earliest check, before cards are built on it.
  2. A1 and A2 aren't wasted if A3 fails. The reasons feed any later way of showing cards (a second pane, or the picker's preview), so they're a foundation with a payoff either way. They stay first.
  3. A3 must leave the sidebar unchanged, row for row. A visible regression there would hit the user's daily sidebar before cards give anything back.
- **Considered and kept:** putting A6 (the segment hiding) before the cards was rejected. Hiding the segment before cards exist would remove the user's signal for a release cycle. No release goes out mid-stack (S14), but A6 is still placed after A4 so the order makes sense on its own.

### Drift test

1. **If every phase after this one were cancelled, would what this PR changed still be right, and would it leave the sidebar, status bar or hooks worse for the user than 1.3.0?** Plumbing with no visible effect is fine; a regression is not.
2. **Does this PR bring the user closer to "see which agent and why, then `G` and Enter to its pane", or is it serving something the Goal doesn't ask for**, such as a card style, a dismiss key, or a history?

## Not doing

- **Cards outside the sidebar:** out of scope. The status bar and alert stay as they are without one (user).
- **Dismissing cards, or a history of them:** rejected (S4).
- **Hiding a card while its agent's pane is visible:** rejected (S4).
- **A global jump-to-card key:** rejected (S7).
- **Raising the fzf floor:** not without the user's say. A3 stops and reports instead.

## Blocked on

- **1.3.0 landing** (the jump to the agent's pane, on `feat/jump-to-agent`): owned by this session's orchestrator. It blocks A1, because Stack A is based on `main` after it.

## Log

- 2026-11-18: plan written from the approved design.
- 2026-11-19: 1.3.0 landed as #26, the base this plan builds on.
- 2026-11-19: A1 landed as #27.
