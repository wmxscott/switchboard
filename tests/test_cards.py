"""The card model: which agents get a card, in what order, and how the stack under the list is
drawn."""

from __future__ import annotations

import re

import pytest

from switchboard import cards
from switchboard.cards import Card
from switchboard.tmux import Pane

RED, GREEN = "38;2;237;135;150", "38;2;166;218;149"
TEXT, SUBTEXT, OVERLAY = "38;2;202;211;245", "38;2;165;173;203", "38;2;128;135;162"


@pytest.fixture(autouse=True)
def dark(monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_THEME", "dark")


def esc(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def agent(
    session: str,
    pane: str = "%1",
    turn: str = "idle",
    pending: tuple[str, ...] = (),
    reasons: tuple[tuple[str, str], ...] = (),
    task: str = "",
    at: int = 0,
    role: str = "lead",
    name: str = "",
) -> Pane:
    return Pane(session, 1, pane, "claude", role, turn, pending, 0, name, reasons, task, at)


def card(session: str, pane: str = "%1", **fields) -> Card:
    found = {"state": "needs", "count": 1, "label": "claude", "why": "needs you", "at": 0}
    return Card(session, pane, **{**found, **fields})


def fields(items: list[str]) -> list[tuple[str, ...]]:
    return [tuple(plain(item).split("\t")) for item in items]


def test_an_agent_that_needs_you_or_is_done_gets_a_card():
    found = cards.build(
        [
            agent("a", "%1", pending=("k",)),
            agent("b", "%2", turn="done"),
            agent("c", "%3", turn="working"),
            agent("d", "%4"),
            agent("e", "%5", pending=("k",), role=""),
        ],
        "",
    )
    assert [(c.session, c.pane, c.state) for c in found] == [
        ("a", "%1", "needs"),
        ("b", "%2", "done"),
    ]


def test_teammates_get_only_needs_you_cards():
    found = cards.build(
        [
            agent("a", "%1", turn="done", role="teammate"),
            agent("a", "%2", turn="working", pending=("k",), role="teammate"),
        ],
        "",
    )
    assert [(c.pane, c.state, c.label) for c in found] == [("%2", "needs", "teammate")]


def test_no_cards_for_the_sidebars_own_session():
    panes = [agent("here", "%1", pending=("k",)), agent("here", "%2", turn="done")]
    assert cards.build([*panes, agent("there", "%3", turn="done")], "here") == [
        Card("there", "%3", "done", 0, "claude", "done", 0)
    ]


def test_oldest_first_by_the_cards_time_and_in_tmuxs_order_on_a_tie():
    found = cards.build(
        [
            agent("a", "%1", turn="done", at=30),
            agent("b", "%2", pending=("k",), at=10),
            agent("c", "%3", turn="done", at=20),
            agent("d", "%4", turn="done", at=10),
        ],
        "",
    )
    assert [c.session for c in found] == ["b", "d", "c", "a"]
    assert [c.at for c in found] == [10, 10, 20, 30]


@pytest.mark.parametrize(
    ("pane", "why"),
    [
        (agent("a", pending=("x",), reasons=(("x", "run: ls"),)), "run: ls"),
        (
            agent("a", pending=("x", "y"), reasons=(("y", "edit: a.py"), ("x", "run: ls"))),
            "run: ls",
        ),
        (agent("a", pending=("x", "y"), reasons=(("x", "run: ls"), ("y", ""))), "needs you"),
        (agent("a", pending=("x",), reasons=(("gone", "run: ls"),)), "needs you"),
        (agent("a", pending=("x",)), "needs you"),
        (agent("a", turn="done", task="fix the login"), "done: fix the login"),
        (agent("a", turn="done"), "done"),
    ],
)
def test_why_is_the_newest_prompts_reason_or_the_finished_task(pane, why):
    (found,) = cards.build([pane], "")
    assert found.why == why


@pytest.mark.parametrize(
    ("pane", "label"),
    [
        (agent("a", pending=("k",)), "claude"),
        (agent("a", pending=("k",), name="codex"), "codex"),
        (agent("a", pending=("k",), name="pi", role="teammate"), "teammate"),
    ],
)
def test_the_label_names_the_agent_as_the_picker_does(pane, label):
    assert cards.build([pane], "")[0].label == label


def test_the_count_is_the_agents_pending_prompts():
    found = cards.build([agent("a", pending=("x", "y", "z")), agent("b", turn="done")], "")
    assert [c.count for c in found] == [3, 0]


@pytest.mark.parametrize(
    ("count", "space", "shown"),
    [
        (1, 3, 1),
        (2, 5, 2),
        (2, 4, 1),
        (5, 11, 5),
        (5, 10, 4),
        (5, 9, 3),
        (3, 2, 1),
        (1, 0, 1),
        (4, -6, 1),
    ],
)
def test_the_oldest_cards_fold_past_what_fits_but_the_newest_always_shows(count, space, shown):
    assert cards.fit(count, space) == shown


def test_no_cards_no_stack():
    assert cards.stack([], 20, 29) == []


def test_the_stack_ends_on_the_last_row_under_a_rule():
    found = cards.stack([card("w/a", "%4", why="run: npm test")], 10, 20)
    assert fields(found) == [
        ("", "", cards.GAP, "\n" * 7 + "─" * 20),
        ("w/a", "%4", "", "▲ w/a · claude\n  run: npm test"),
    ]
    assert found[0].endswith(f"\t{chr(10) * 7}{esc(OVERLAY, '─' * 20)}")
    line1, line2 = found[1].split("\t")[3].split("\n")
    assert line1 == f"{esc(RED, '▲')}{esc(TEXT, ' w/a')}{esc(SUBTEXT, ' · claude')}"
    assert line2 == esc(SUBTEXT, "  run: npm test")


def test_a_done_card_is_green_and_several_prompts_count_on_the_mark():
    found = cards.stack(
        [card("a", "%1", state="done", count=0, why="done: x"), card("b", "%2", count=2)], 5, 29
    )
    assert [display.split("\n")[0] for *_, display in fields(found[1:])] == [
        "✓ a · claude",
        "▲² b · claude",
    ]
    assert found[1].split("\t")[3].startswith(esc(GREEN, "✓"))
    assert found[2].split("\t")[3].startswith(esc(RED, "▲²"))


def test_the_oldest_fold_into_more_at_the_top_of_the_stack():
    found = cards.stack([card(name, f"%{n}") for n, name in enumerate("abcde")], 6, 29)
    assert fields(found) == [
        ("", "", cards.GAP, "─" * 29),
        ("", "", "", "+3 more"),
        ("d", "%3", "", "▲ d · claude\n  needs you"),
        ("e", "%4", "", "▲ e · claude\n  needs you"),
    ]
    assert found[1].endswith(esc(SUBTEXT, "+3 more"))


def test_a_stack_too_tall_for_its_space_has_an_empty_gap():
    found = cards.stack([card("a"), card("b")], -3, 29)
    assert fields(found)[:2] == [("", "", cards.GAP, "─" * 29), ("", "", "", "+1 more")]
    assert len(found) == 3


def test_both_lines_are_cut_to_the_width():
    long = card("w/feature/very-long-name", why="run: pytest -q tests/test_everything.py")
    (_, found) = cards.stack([long], 3, 20)
    line1, line2 = found.split("\t")[3].split("\n")
    assert (plain(line1), plain(line2)) == ("▲ w/feature/very-lo…", "  run: pytest -q te…")
    assert line1 == f"{esc(RED, '▲')}{esc(TEXT, ' w/feature/very-lo…')}"
    assert line2 == esc(SUBTEXT, "  run: pytest -q te…")


def test_a_cut_in_the_label_keeps_each_parts_colour():
    (_, found) = cards.stack([card("w/a", label="teammate")], 3, 12)
    line1 = found.split("\t")[3].split("\n")[0]
    assert line1 == f"{esc(RED, '▲')}{esc(TEXT, ' w/a')}{esc(SUBTEXT, ' · tea…')}"
