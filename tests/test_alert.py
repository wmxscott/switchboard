"""The alert's rule, its messages, and its sound against a stub `afplay`."""

from __future__ import annotations

import pytest

from switchboard import alert

NEWS = [
    ("lead:working:", "lead:working:lead", "needs"),
    ("lead:idle:", "lead:idle:a1", "needs"),
    ("teammate:working:", "teammate:working:lead", "needs"),
    ("lead:working:a1", "lead:working:a1,lead", None),
    ("lead:working:", "lead:done:", "done"),
    ("lead:working:a1,lead", "lead:done:a1", None),
    ("lead:working:a1", "lead:done:a1", None),
    (":working:", "lead:done:", "done"),
    ("teammate:working:", "teammate:idle:", None),
    ("lead:working:", "lead:idle:", None),
    ("lead:done:a1", "lead:done:", "done"),
    ("teammate:done:a1", "teammate:done:", None),
    ("lead:done:", "lead:done:", None),
    ("lead:working:lead", "lead:working:", None),
    ("lead:done:", "lead:working:", None),
]


@pytest.mark.parametrize(("before", "after", "news"), NEWS)
def test_news(before, after, news):
    assert alert.news(tuple(before.split(":")), tuple(after.split(":"))) == news


def test_send_messages_every_client_in_one_call_with_one_sound(stubs, monkeypatch):
    played = []
    monkeypatch.setattr(alert, "play", lambda: played.append(True))
    alert.send("needs", "repo/fix#[1]", ["/dev/ttys001", "/dev/ttys002"])
    assert stubs.tmux.calls() == [
        [
            *("display-message", "-c", "/dev/ttys001", "-d", "4000", "▲ repo/fix##[1] needs you"),
            *(";", "display-message", "-c", "/dev/ttys002", "-d", "4000"),
            "▲ repo/fix##[1] needs you",
        ]
    ]
    assert played == [True]


def test_done_reads_is_done(stubs, monkeypatch):
    monkeypatch.setattr(alert, "play", lambda: None)
    alert.send("done", "repo/main", ["/dev/ttys001"])
    assert stubs.tmux.calls()[0][-1] == "✓ repo/main is done"


def test_no_client_means_no_message_and_no_sound(stubs, monkeypatch):
    played = []
    monkeypatch.setattr(alert, "play", lambda: played.append(True))
    alert.send("needs", "repo/main", [])
    assert stubs.tmux.calls() == []
    assert played == []


def played_files(stubs, proc) -> list[list[str]]:
    assert proc is not None
    assert proc.wait(timeout=10) == 0
    return stubs.afplay.calls()


def test_the_default_sound_is_the_first_system_sound_that_exists(stubs, tmp_path, monkeypatch):
    assert alert.SOUNDS[0] == "/System/Library/Sounds/Glass.aiff"
    present = tmp_path / "Tink.aiff"
    present.write_bytes(b"")
    monkeypatch.setattr(alert, "SOUNDS", (str(tmp_path / "Glass.aiff"), str(present)))
    assert played_files(stubs, alert.play()) == [[str(present)]]


def test_switchboard_sound_overrides_the_default(stubs, monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_SOUND", "/sounds/chime.aiff")
    assert played_files(stubs, alert.play()) == [["/sounds/chime.aiff"]]


def test_an_empty_switchboard_sound_turns_the_sound_off(stubs, monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_SOUND", "")
    assert alert.sound() is None
    assert alert.play() is None
    alert.send("needs", "repo/main", ["/dev/ttys001"])
    assert [call[0] for call in stubs.tmux.calls()] == ["display-message"]
    assert stubs.afplay.calls() == []


def test_no_sound_without_a_system_sound(stubs, tmp_path, monkeypatch):
    monkeypatch.setattr(alert, "SOUNDS", (str(tmp_path / "missing.aiff"),))
    assert alert.play() is None
    assert stubs.afplay.calls() == []


def test_no_afplay_means_no_sound_and_no_error(stubs, tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_SOUND", "/sounds/chime.aiff")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert alert.play() is None
    alert.send("done", "repo/main", ["/dev/ttys001"])
    assert stubs.afplay.calls() == []


def test_a_player_that_cannot_start_is_ignored(stubs, monkeypatch):
    monkeypatch.setenv("SWITCHBOARD_SOUND", "/sounds/chime.aiff")
    stub = stubs.afplay.log_path.parent / "bin" / "afplay"
    stub.chmod(0o644)
    monkeypatch.setattr(alert.shutil, "which", lambda name: str(stub))
    assert alert.play() is None
