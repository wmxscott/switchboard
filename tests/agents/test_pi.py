"""Pi's adapter through `switchboard hook --agent pi`, with the ai-toolkit extension's events and
`{"event": ...}` payloads."""

from __future__ import annotations

import pytest

from switchboard import panestate

DONE = [(client, "✓ work is done") for client in ("/dev/ttys001", "/dev/ttys002")]


@pytest.fixture
def pi(drive):
    return drive("pi", "event")


MAPPING = [
    ("session_start", {"reason": "startup", "idle": True}, "::", "lead:idle:"),
    ("session_start", {"reason": "resume", "idle": False}, "::", "lead:working:"),
    ("session_start", {"reason": "new", "idle": True}, "lead:done:p1,ui", "lead:idle:"),
    ("session_start", {"reason": "startup"}, "lead:working:", "lead:idle:"),
    ("agent_start", {}, "lead:idle:", "lead:working:"),
    ("agent_start", {}, "lead:done:", "lead:working:"),
    ("agent_start", {}, "lead:working:", None),
    ("ui_prompt_start", {"kind": "confirm"}, "lead:working:", "lead:working:ui"),
    ("ui_prompt_end", {}, "lead:working:p1,ui", "lead:working:p1"),
    ("plannotator_opened", {"id": "p1"}, "lead:working:ui", "lead:working:p1,ui"),
    ("plannotator_closed", {"id": "p1"}, "lead:idle:p1,ui", "lead:idle:ui"),
    ("agent_settled", {"aborted": False}, "lead:working:p1,ui", "lead:done:"),
    ("agent_settled", {"aborted": True}, "lead:working:", "lead:idle:"),
    ("agent_settled", {"aborted": True}, "lead:working:ui", "lead:idle:ui"),
]


@pytest.mark.parametrize(("event", "payload", "before", "expected"), MAPPING)
def test_event_mapping(pi, event, payload, before, expected):
    pi.stored(before)
    pi.fire(event, **payload)
    assert pi.after() == expected
    assert pi.calls()[0] == pi.read


REASONS = [
    ("ui_prompt_start", {"kind": "confirm", "title": "Delete 3 files?"}, "ui", "Delete 3 files?"),
    ("ui_prompt_start", {"kind": "select", "title": "Pick a model\nfor now"}, "ui", "Pick a model"),
    ("ui_prompt_start", {"kind": "select"}, "ui", "select"),
    ("ui_prompt_start", {"kind": "input", "title": " "}, "ui", "input"),
    ("ui_prompt_start", {"kind": "editor", "title": 5}, "ui", "editor"),
    ("ui_prompt_start", {"kind": ["custom"]}, "ui", ""),
    ("ui_prompt_start", {}, "ui", ""),
    ("plannotator_opened", {"id": "p1"}, "p1", "plan ready for review"),
]


@pytest.mark.parametrize(("event", "payload", "key", "reason"), REASONS)
def test_each_prompt_gives_its_reason(pi, event, payload, key, reason):
    pi.stored("lead:working:")
    pi.fire(event, **payload)
    assert pi.after() == f"lead:working:{key}"
    assert pi.reasons() == {key: reason}


def test_a_nested_dialog_with_the_same_reason_writes_nothing(pi):
    pi.stored("lead:working:ui", reasons={"ui": "custom"})
    pi.fire("ui_prompt_start", kind="custom")
    assert pi.calls() == [pi.read]


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        ("lead:idle:", "lead:idle:"),
        ("lead:working:ui", "lead:working:ui"),
        ("lead:done:", "lead:done:"),
        ("::", "lead:idle:"),
    ],
)
def test_input_sets_the_task_and_leaves_the_turn_to_the_run(pi, before, expected):
    """An extension can handle the input itself, and then no run starts."""
    pi.stored(before, task="Earlier task")
    pi.fire("input", text="Refactor the parser\nand add tests")
    assert pi.after() == expected
    assert pi.task() == "Refactor the parser"
    assert panestate.CARD_AT not in pi.written()


@pytest.mark.parametrize("payload", [{}, {"text": None}, {"text": ["fix it"]}, {"text": " \n"}])
def test_input_with_no_text_changes_nothing(pi, payload):
    pi.stored("lead:idle:")
    pi.fire("input", **payload)
    assert pi.calls() == [pi.read]


def test_a_settled_run_keeps_its_task(pi):
    pi.stored("lead:working:", task="Refactor the parser")
    pi.fire("agent_settled", aborted=False)
    assert (pi.after(), pi.task()) == ("lead:done:", "Refactor the parser")


def test_a_settled_run_in_a_session_a_client_is_viewing_goes_idle(pi):
    pi.stored("lead:working:", viewed=True)
    pi.fire("agent_settled", aborted=False)
    assert pi.after() == "lead:idle:"


def test_pi_sends_no_session_id_so_its_pane_never_holds_one(pi):
    pi.stored("::")
    pi.fire("session_start", reason="startup", idle=True, session_id="s1")
    assert pi.after() == "lead:idle:"
    assert pi.written()[panestate.SESSION_ID] is None


def test_quitting_ends_the_session(pi):
    pi.stored()
    pi.fire("session_shutdown", reason="quit")
    assert pi.written() == dict.fromkeys(panestate.OPTIONS)
    assert [call[0] for call in pi.calls()] == ["display-message", "set-option", "list-sessions"]


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        *(("session_shutdown", {"reason": r}) for r in ("reload", "new", "resume", "fork")),
        ("plannotator_opened", {}),
        ("plannotator_opened", {"id": 7}),
        ("plannotator_closed", {"id": ""}),
        ("turn_start", {}),
        ("SessionStart", {}),
    ],
)
def test_events_that_change_nothing_never_call_tmux(pi, event, payload):
    pi.stored()
    pi.fire(event, **payload)
    assert pi.calls() == []


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [
        ("ui_prompt_start", {"kind": "select"}, ("/dev/ttys001", "▲ work needs you")),
        ("plannotator_opened", {"id": "p1"}, ("/dev/ttys001", "▲ work needs you")),
        ("agent_settled", {"aborted": False}, DONE[0]),
        ("agent_settled", {"aborted": True}, None),
    ],
)
def test_needs_you_and_a_settled_run_alert_but_an_abort_does_not(pi, event, payload, expected):
    pi.stored("lead:working:")
    pi.fire(event, **payload)
    assert pi.alerts()[:1] == ([expected] if expected else [])


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("agent_start", {}),
        ("ui_prompt_start", {}),
        ("input", {"text": "Refactor the parser"}),
        ("session_shutdown", {"reason": "quit"}),
    ],
)
def test_events_from_outside_the_pane_are_dropped(pi, ps, event, payload):
    pi.stored("lead:idle:", inside=False)
    pi.fire(event, **payload)
    assert pi.calls() == [pi.read]
    assert ps.calls() == ["-axo pid=,ppid="]
