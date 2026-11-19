"""Drives an adapter through `switchboard hook --agent NAME` against the stub tmux and `ps`.

A pane's state is written `role:turn:pending`, as in `lead:working:a1,lead`. The pane's process
is an ancestor of this one, as the stub `ps` tells it, unless a test says it's outside.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from switchboard import alert, hook, panestate

PANE = "%7"
INSIDE, OUTSIDE = 400, 999
READ = [
    *("display-message", "-p", "-t", PANE),
    "#{session_name}\t#{@switchboard-role}\t#{@switchboard-turn}\t#{@switchboard-pending}"
    "\t#{@switchboard-reasons}\t#{@switchboard-task}\t#{@switchboard-session-id}\t#{pane_pid}",
    *(
        ";",
        "list-clients",
        "-F",
        "#{client_name}\t#{?#{P:#{@switchboard-sidebar}},1,}\t#{client_session}",
    ),
]


def commands(call: list[str]) -> list[list[str]]:
    found: list[list[str]] = [[]]
    for arg in call:
        if arg == ";":
            found.append([])
        else:
            found[-1].append(arg)
    return found


@dataclass
class Driver:
    stubs: object
    agent: str
    field: str
    pane = PANE
    read = READ

    def stored(
        self,
        state: str = "lead:working:",
        viewed: bool = False,
        inside: bool = True,
        reasons: dict[str, str] | None = None,
        task: str = "",
        session_id: str = "",
    ):
        """The pane is in `work`, holding `reasons`, `task` and `session_id`, and two clients are
        elsewhere, or one is on `work`."""
        pid = INSIDE if inside else OUTSIDE
        why = panestate.encode_reasons(reasons or {})
        task = panestate.encode_task(task)
        lines = [
            "work\t" + state.replace(":", "\t") + f"\t{why}\t{task}\t{session_id}\t{pid}",
            "/dev/ttys001\t\t" + ("work" if viewed else "elsewhere"),
            "/dev/ttys002\t\tother",
        ]
        self.stubs.tmux.answer("display-message", stdout="\n".join(lines) + "\n")

    def fire(self, event: str, **fields) -> None:
        payload = json.dumps({self.field: event, **fields}).encode()
        hook.handle(["--agent", self.agent, event], PANE, payload)

    def calls(self) -> list[list[str]]:
        return self.stubs.tmux.calls()

    def written(self) -> dict[str, str | None] | None:
        """The options the single write set, None for each it unset; None for no write."""
        writes = [call for call in self.calls() if call[0] == "set-option"]
        assert len(writes) <= 1
        if not writes:
            return None
        options: dict[str, str | None] = {}
        for command in commands(writes[0]):
            unset = command[2] == "-u"
            options[command[-1] if unset else command[-2]] = None if unset else command[-1]
        return options

    def after(self) -> str | None:
        """The state written, after checking the write labels the pane with the agent."""
        options = self.written()
        if options is None:
            return None
        assert options[panestate.AGENT] == self.agent
        names = (panestate.ROLE, panestate.TURN, panestate.PENDING)
        return ":".join(options[name] or "" for name in names)

    def reasons(self) -> dict[str, str] | None:
        """The reasons written, None for no write."""
        options = self.written()
        return options and panestate.decode_reasons(options[panestate.REASONS] or "")

    def task(self) -> str | None:
        """The task written, None for no write."""
        options = self.written()
        return options and panestate.decode_task(options[panestate.TASK] or "")

    def alerts(self) -> list[tuple[str, str]]:
        return [
            (command[2], command[5])
            for call in self.calls()
            for command in commands(call)
            if command[:2] == ["display-message", "-c"]
        ]


@pytest.fixture
def drive(stubs, ps, monkeypatch):
    """`drive(agent, field)` drives `agent`, whose payloads name their event in `field`. The
    alert's sound is off."""
    monkeypatch.setattr(alert, "play", lambda: None)
    return lambda agent, field: Driver(stubs, agent, field)
