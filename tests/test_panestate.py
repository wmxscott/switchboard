"""The pane options' encoding and the state derived from them."""

from __future__ import annotations

import pytest

from switchboard import panestate as ps


def test_pending_round_trips_sorted_and_without_duplicates():
    value = ps.encode_pending(["toolu_2", ps.LEAD_KEY, "a1b2c3", ps.LEAD_KEY, ""])
    assert value == "a1b2c3,lead,toolu_2"
    assert ps.decode_pending(value) == ("a1b2c3", "lead", "toolu_2")


@pytest.mark.parametrize("key", ["a,b", "a\tb", "a\nb", "a;b", "a b", "a#{b}"])
def test_pending_never_holds_a_separator(key):
    value = ps.encode_pending([key, "lead"])
    assert not set(value) & set(";\t\n #{}")
    assert len(ps.decode_pending(value)) == 2


@pytest.mark.parametrize("value", ["", ",", ",,"])
def test_empty_pending(value):
    assert ps.decode_pending(value) == ()
    assert ps.encode_pending([]) == ""


@pytest.mark.parametrize(
    ("turn", "pending", "state"),
    [
        ("working", ("lead",), "needs"),
        ("idle", ("a1",), "needs"),
        ("done", (), "done"),
        ("working", (), "working"),
        ("idle", (), "idle"),
        ("", (), "idle"),
        ("bogus", (), "idle"),
    ],
)
def test_display_state(turn, pending, state):
    assert ps.display(turn, pending) == state


def test_urgency_order():
    assert ps.URGENCY == ("needs", "done", "working", "idle")
    assert ps.most_urgent(["idle", "working", "done"]) == "done"
    assert ps.most_urgent(["idle", "needs", "done"]) == "needs"
    assert ps.most_urgent(["idle", "working"]) == "working"
    assert ps.most_urgent([]) is None


def test_option_names():
    assert ps.OPTIONS == (
        "@switchboard-role",
        "@switchboard-turn",
        "@switchboard-pending",
        "@switchboard-at",
    )
