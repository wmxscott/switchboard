# switchboard: agent cards in the sidebar

**Status:** draft, waiting for the user's approval. The builder check is done (2026-11-18), and its questions are answered here.

## Why

The sidebar (1.2) puts the picker's list in a pane down the left of a window and keeps it there. The user's idea is to use it for agent notifications too, instead of the status bar. When an agent needs them or finishes, they want to know **which agent, and why, so they can jump there**. Cards pop in at the bottom of the sidebar, stacked.

They get there by moving into the sidebar, putting the cursor on the card and pressing Enter, which lands on that agent's pane. That jump comes from 1.3.0, which is in progress: picking a session lands on its agent's pane, and the picker's agent rows become pickable. This design builds on 1.3.0.

## Goals (the user's decisions)

- **Which agents:** a card for each agent that needs you or is done.
- **What a card says:** the agent, as its session and its name, and why it needs you, or what it finished.
- **Picking:** with the sidebar's keys (`j`/`k`, Enter). Enter lands on the agent's pane (`switch-client -t %PANE`). There's no global key that jumps to a card.
- **`G` and `g`, like vim:** `G` jumps to the newest card, at the very bottom, and `g` jumps to the top of the list. The user picked these over Ctrl-D and Ctrl-U, which already delete a worktree in wkt's picker.
- **The cursor never moves by itself:** not when a card arrives, and not when you move into the sidebar.
- **When a card goes:** when you've answered that agent (needs you) or visited it (done). A card follows the agent's state and is never dismissed by hand.
- **Look, style "A":**
  - plain, with two lines per card, under a rule;
  - the newest at the bottom, pushing older ones up;
  - the stack sits at the bottom of the sidebar.
- **One card is one fzf item:** the cursor selects both lines together, and never stops on a card's second line.
- **The status bar:** while the window you're looking at has a sidebar, its ▲✓ segment hides, because the cards replace it.
- **The sound:** the alert sound stays.
- **A full stack:** when the cards don't fit, the oldest fold into one `+N more` line at the top of the stack.

The mockup the user picked style A from is `brainstorm-cards/…/cards-layout.html` in the session scratchpad. It's not committed, and this section is the record of it:

```
▾ widget
│ ◉ main                     ○
│   fix-login                ●
│   docs                     ●
▸ gadget ●
▾ other
│   notes

(empty, never a cursor stop)

────────────────────────────────
✓ gadget/main · codex
  done: refactor the parser
▲ widget/docs · pi
  asks: keep the old API?
▲ widget/fix-login · claude      ← newest, cursor here
  run: npm test
```

## Non-goals

- Cards anywhere but in the sidebar. Without a sidebar, the status bar and the alert stay as they are.
- A history of past notifications.
- Dismissing a card by hand.
- Changes to the full picker beyond what 1.3.0 does.

## Anti-goals: what would make it a failure even if it works

- A card that outlives its state, still there after you answered or visited, or one whose "why" is wrong. Either is worse than no card.
- The cursor stopping on the empty gap or on a card's second line.
- Slower hooks. The hook runs on every agent event and has a fast path with no heavy imports, and reading the reason must keep it that way.
- Breaking the picker, the status bar or the alert for anyone who never opens a sidebar.

## Card content

**Line 1:** the mark (red ▲ for needs you, green ✓ for done), the session name, then `· ` and the agent's label (`claude`, `codex`, `pi`, or a teammate's name). Cut to the sidebar's width with `…`. When one agent has several prompts pending, the mark gets a superscript count (`▲²`), as in the status bar.

**Line 2:** the "why", indented two columns and cut with `…`.

| Agent and event | Line 2 |
|---|---|
| Claude `PermissionRequest`, Bash | `run: <command>` |
| Claude `PermissionRequest`, a tool with a file path (Edit, Write and others) | `edit: <path>`, or `<verb>: <path>` |
| Claude `PermissionRequest`, anything else | the tool's name |
| Claude `PreToolUse` `AskUserQuestion` | `asks: <first question>` |
| Claude `PreToolUse` `ExitPlanMode` | `plan ready for review` |
| Claude `Notification` (`permission_prompt`, `elicitation_*`) | its `message` |
| Codex `PermissionRequest` (Claude-shaped payload) | as Claude |
| Codex `PreToolUse` `request_user_input` | `asks: <first question>` |
| Pi `ui_prompt_start` | its `title`, else its `kind` |
| Pi Plannotator opened | `plan ready for review` |
| Done, any agent | `done: <first line of the prompt that started the turn>`, or `done` if unknown |

- The prompt for "done" comes from Claude's and Codex's `UserPromptSubmit` `prompt`, and from Pi's `input` event.
- With several pending prompts, line 2 shows the most recent one's reason.
- Every reason is stored as one line: control characters stripped, nothing tmux treats specially left in, and capped at about 200 characters when it's stored. It's only cut to fit when drawn.
- The exact wording of the "why" for each tool is the builder's call, within the table's spirit: short, and the thing you'd answer.

## Where the reasons live

- **Today:**
  - each agent's state is in its pane's options (`panestate.py`);
  - `@switchboard-pending` holds the pending prompt keys, comma-separated;
  - `@switchboard-at` holds the Unix seconds of the last change.
- **New pane options** hold a reason for each pending key, so that resolving one key leaves the others' reasons right, plus the line of the current turn's prompt. Their names and encoding are the builder's call, and must be tmux-safe like `encode_pending`.
- **Each adapter** (`agents/claude.py`, `codex.py`, `pi.py`) says what the reason is, so a contributor adding an agent adds its reasons in the same place. README's "Adding an agent" covers this.
- **Pi** reports through `switchboard hook --agent pi <event>` with JSON, like the other agents, so its reasons come through `agents/pi.py`. The ai-toolkit extension (`pi/extensions/switchboard.ts`) starts sending `title` on `ui_prompt_start` and forwards Pi's `input` event. That change is a follow-up in ai-toolkit, outside this plan's stack. An older switchboard ignores the new field and event, so the two can update in either order. Until the extension lands, Pi's cards say `needs you` or `done`.
- **`switchboard state`** (for tools without an adapter) takes an optional reason with `needs`, and an optional prompt line with `working`, for example `--reason TEXT` and `--task TEXT`. The flag names are the builder's call. Today's calls keep working unchanged.
- **Card order** is when the card appeared: for needs you, when its latest prompt arrived; for done, when the turn ended. The builder checks whether `@switchboard-at` already changes on exactly those moves, and adds a timestamp only if it doesn't.

## The sidebar

- **The list at the top is unchanged.**
- **The stack sits at the bottom:** a rule, then the cards, oldest first and newest last.
  - The space between the list and the rule is empty, and the cursor never stops there. `j` from the last list row goes to the first card, and `k` comes back.
  - How the gap is filled and skipped is the builder's call. One lead: a single blank multi-line item, which a `transform` on `j`/`k` steps over.
  - With no cards, there's no rule and no gap.
- **One card is one item:** each item becomes NUL-separated (`--read0`; fzf has shown items across lines since 0.53, and the floor is 0.59). That touches every consumer of the item text:
  - `{1}` in `__switch`, the folds and `pos()`;
  - the current-session marker;
  - search;
  - the reload that a poke sends.

  All of them must keep working.
- **When it's crowded (my call):** the cards stay visible and the list gives way. When the list alone is taller than the pane, the list scrolls and the stack stays put at the bottom, so a card never sits off-screen.
  - In one fzf, this needs the cards to be the items fzf draws first. One lead: the `default` layout, which draws from the bottom up, with the cards first in the input and the list after them, reversed.
  - If the cards still don't fit in what's left after a few list rows, the oldest fold into `+N more`. Enter on `+N more` does nothing.
- **Across redraws** the cursor stays on the same item, by identity rather than by row number. If its card has gone, it moves to the nearest card, or to the list when there are none, so Enter never lands on a different agent than the one under the cursor. fzf's `--id-nth` would do this, but it needs fzf 0.71, so with the 0.59 floor the redraw works out `pos()` itself. How is the builder's call.
- **`G` and `g`** are bound like `j`/`k`: off while searching, and back on when the search ends. `G` with no cards goes to the last list row.
- **Enter on a card** lands on that agent's pane, with 1.3.0's jump and its fallback to the session if the pane has gone. The sidebar stays in its window, as today.
- **Search** (`/`) matches cards as well as list rows.
- **No cards for the sidebar's own session (my call):** it follows the status bar, which never lists your own session.
  - Done never happens in a session someone is viewing (an existing rule).
  - A needs-you card lasts as long as the state does, and the state lasts in two cases the user already accepted for the status bar:
    - a slow approved command keeps "needs you" until it ends, because Claude Code sends no event between the approval and the tool's end;
    - a rejected or interrupted prompt keeps it until your next typed prompt.

    In your own session, such a card would sit beside you the whole time. Elsewhere, it behaves exactly as ▲ does today.
- **Teammates** get needs-you cards like any agent. They never reach done.
- **No polling:** the cards come and go on the same poke that redraws the sidebar today.

## The status bar

- A client whose current window has a sidebar shows no ▲✓ segment, and no `prefix w` hint either (my call: the whole segment hides). Other clients and windows are unchanged.
- The approach is the builder's call. One lead: tmux's `#{P:…}` loops over a window's panes, so switchboard could wrap the `@attention` format it writes in `#{?#{P:#{@switchboard-sidebar}},,…}`. That needs no change to anyone's tmux config. Check it with `#{E:@attention}` on tmux 3.8.

## The alert

- The sound plays for every alert, as today.
- **The message (my call):** clients whose current window has a sidebar skip it, because the card already says the same thing. Other clients still get it.

## Constraints

- tmux 3.8, fzf 0.59 or later, and Python 3.11 or later. CI runs on macOS and Linux.
- Tests never touch the user's tmux server. Real checks use `tmux -L <name> -f /dev/null`.
- The hook's fast path stays free of heavy imports.
- Lands as a stacked plan in `docs/plans/`, with a 400-line production cap per PR.
- **Released as 1.4.0** (1.3.0 is the jump change). The ai-toolkit Pi extension follows separately (see "Where the reasons live").

## Left to the builder

- The names and encoding of the new pane options.
- The "why" wording for each tool.
- How the gap is drawn and skipped.
- How many cards fit.
- Whether `@switchboard-at` is enough to order cards.
- How the status bar hides its segment.

## Risks

- **`--read0`** changes how every sidebar item is built and read. The 0.59 floor needs a real check, not just 0.75.
- **A "why" can hold a secret**, such as a token in a command line. It's stored in a pane option, which only the user's own tmux server can read, and shown on their own screen, where the agent's prompt already shows it. That's acceptable, but worth a line in the README.
- **Reasons come from payload fields that agents may rename.** A missing field must give a plain card (`needs you`, or `done`), never an error in the hook.
