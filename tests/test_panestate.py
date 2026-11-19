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
        "@switchboard-agent",
        "@switchboard-reasons",
        "@switchboard-task",
        "@switchboard-card-at",
    )


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("run: ls", "run: ls"),
        ("  fix\tthe\r\nlogin\n\n", "fix the login"),
        ("a\x1b[31mb\x07c\x7fd\x9be", "a[31mbcde"),
        ("one\u2028two\x85three\x1fdone", "one two three done"),
        ("a \x00 b", "a b"),
        ("ça va? ▲ #{x} a, b; c;", "ça va? ▲ #{x} a, b; c;"),
        ("\n\t ", ""),
    ],
)
def test_one_line(text, line):
    assert ps.one_line(text) == line


def test_one_line_is_capped():
    assert ps.one_line("x" * 250) == "x" * ps.CAP
    assert ps.one_line(f"{'x' * (ps.CAP - 1)} y") == "x" * (ps.CAP - 1)
    assert ps.CAP == 200


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("Fix the login bug\n\nIt fails on Safari.", "Fix the login bug"),
        ("\n  \r\n  add tests\r\nthen lint", "  add tests"),
        ("one line", "one line"),
        ("", ""),
        ("\n\t\n", ""),
        (None, ""),
        (42, ""),
        (["fix it"], ""),
    ],
)
def test_first_line(text, line):
    assert ps.first_line(text) == line


TRICKY = 'a, b; c=d #{e} "f" \\ ▲ ;'


def test_reasons_round_trip_in_arrival_order():
    reasons = {"lead": "run: ls;", "a1": TRICKY, "b2": "", "c3": "x\ty\nz"}
    value = ps.encode_reasons(reasons)
    assert list(ps.decode_reasons(value).items()) == list(reasons.items())
    assert not set(value) & set("\t\n")
    assert not value.endswith(";")


def test_task_round_trips():
    value = ps.encode_task(TRICKY)
    assert ps.decode_task(value) == TRICKY
    assert not set(value) & set("\t\n")
    assert not value.endswith(";")


def test_nothing_is_stored_as_empty():
    assert ps.encode_reasons({}) == ""
    assert ps.encode_task("") == ""
    assert ps.decode_reasons("") == {}
    assert ps.decode_task("") == ""


@pytest.mark.parametrize(
    ("value", "reasons"),
    [("garbage", {}), ('"text"', {}), ("[1]", {}), ("{", {}), ('{"a":1,"b":"ok"}', {"b": "ok"})],
)
def test_unreadable_reasons_keep_only_their_strings(value, reasons):
    assert ps.decode_reasons(value) == reasons


@pytest.mark.parametrize("value", ["garbage", "{}", "1", '"unclosed'])
def test_an_unreadable_task_is_none(value):
    assert ps.decode_task(value) == ""
