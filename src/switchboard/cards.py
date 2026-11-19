"""The sidebar's cards: one for each agent in another session that needs the user or is done,
oldest first, under the list. A card is one fzf item across two lines, carrying its agent's pane.

Above the cards, a gap item that ends in a rule pushes them down to the pane's last row. Its group
field is `GAP`, which the sidebar's `j` and `k` step over.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from switchboard import panestate as ps
from switchboard.attention import MARK, superscript
from switchboard.picker import DIM, LINE, SGR, TEXT, label, sgr
from switchboard.tmux import Pane

GAP = "gap"
RULE = "─"


@dataclass(frozen=True)
class Card:
    session: str
    pane: str
    state: str
    count: int
    label: str
    why: str
    at: int


def build(agents: Iterable[Pane], own: str) -> list[Card]:
    """The cards for `agents` outside the `own` session, oldest first: one for each agent that
    needs the user, and each lead that's done."""
    found = [
        Card(a.session, a.id, a.state, len(a.pending), label(a), _why(a), a.card_at)
        for a in agents
        if a.is_agent and a.session != own and _shown(a)
    ]
    return sorted(found, key=lambda card: card.at)


def fit(count: int, space: int) -> int:
    """How many of `count` cards show in `space` rows, under the rule and any `+N more`: the
    newest at least, so that a list taller than the pane still scrolls down to one."""
    if 1 + 2 * count <= space:
        return count
    return min(count, max(1, (space - 2) // 2))


def stack(cards: Sequence[Card], space: int, width: int) -> list[str]:
    """The items under the list, ending on the last of its `space` rows when they fit, with each
    line cut to `width`: the gap and its rule, `+N more` for the oldest cards, then the rest."""
    if not cards:
        return []
    shown = fit(len(cards), space)
    folded = len(cards) - shown
    blank = max(0, space - 1 - bool(folded) - 2 * shown)
    items = [_item("", "", GAP, "\n" * blank + sgr(LINE, RULE * width))]
    if folded:
        items.append(_item("", "", "", sgr(DIM, f"+{folded} more")))
    return items + [_card(card, width) for card in cards[folded:]]


def _shown(agent: Pane) -> bool:
    return agent.state == ps.NEEDS or (agent.state == ps.DONE and agent.role != ps.TEAMMATE)


def _why(agent: Pane) -> str:
    if agent.state == ps.DONE:
        return f"done: {agent.task}" if agent.task else "done"
    reasons = [reason for key, reason in agent.reasons if key in agent.pending]
    return (reasons[-1] if reasons else "") or "needs you"


def _card(card: Card, width: int) -> str:
    mark = MARK[card.state] + superscript(card.count)
    head = [(SGR[card.state], mark), (TEXT, f" {card.session}"), (DIM, f" · {card.label}")]
    lines = (_cut(head, width), _cut([(DIM, f"  {card.why}")], width))
    return _item(card.session, card.pane, "", "\n".join(lines))


def _cut(parts: Sequence[tuple[str, str]], width: int) -> str:
    """`parts`, each a style and its text, cut to `width` with `…`."""
    text = "".join(part for _, part in parts)
    shown = text if len(text) <= width else text[: max(width - 1, 0)] + "…"
    drawn, start = [], 0
    for style, part in parts:
        piece = shown[start : start + len(part)]
        start += len(part)
        drawn.append(sgr(style, piece) if piece else "")
    return "".join(drawn)


def _item(session: str, pane: str, group: str, display: str) -> str:
    return f"{session}\t{pane}\t{group}\t{display}"
