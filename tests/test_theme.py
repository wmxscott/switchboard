"""Choosing the picker's theme."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from switchboard import theme


@pytest.fixture
def macos(monkeypatch):
    """macOS answering `style` for its appearance, or failing when None, with each call kept."""
    calls = []

    def answer(style):
        def output(*argv, timeout=None):
            calls.append(list(argv))
            return style

        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(theme.run, "output", output)
        return calls

    return answer


def trigger(folder: str | Path, text: str) -> None:
    path = Path(folder, "theme-monitor", "theme-change.trigger")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_variable_beats_the_trigger_file(monkeypatch, macos):
    calls = macos("Dark\n")
    trigger(os.environ["XDG_DATA_HOME"], "dark\n")
    monkeypatch.setenv("SWITCHBOARD_THEME", "Light")
    assert theme.detect() == "light"
    assert calls == []


@pytest.mark.parametrize("value", ["", "auto", "bogus"])
def test_other_values_mean_auto(monkeypatch, macos, value):
    macos(None)
    trigger(os.environ["XDG_DATA_HOME"], " dark\n")
    monkeypatch.setenv("SWITCHBOARD_THEME", value)
    assert theme.detect() == "dark"


def test_the_trigger_file_follows_xdg_data_home(monkeypatch, macos, tmp_path):
    macos(None)
    trigger(Path.home() / ".local/share", "dark\n")
    trigger(tmp_path / "xdg", "light\n")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert theme.detect() == "light"
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    assert theme.detect() == "dark"


@pytest.mark.parametrize(("style", "found"), [("Dark\n", "dark"), (None, "light")])
def test_without_a_usable_trigger_file_macos_decides(macos, style, found):
    calls = macos(style)
    trigger(os.environ["XDG_DATA_HOME"], "blue\n")
    assert theme.detect() == found
    assert calls == [["defaults", "read", "-g", "AppleInterfaceStyle"]]


def test_elsewhere_light(monkeypatch, macos):
    calls = macos("Dark\n")
    monkeypatch.setattr(sys, "platform", "linux")
    assert theme.detect() == "light"
    assert calls == []


@pytest.mark.parametrize(
    ("chosen", "style", "sgr"),
    [
        ("dark", "green", "38;2;166;218;149"),
        ("dark", "bold text", "1;38;2;202;211;245"),
        ("light", "dim overlay0", "2;38;2;156;160;176"),
        ("light", "peach", "38;2;254;100;11"),
    ],
)
def test_sgr(monkeypatch, chosen, style, sgr):
    monkeypatch.setenv("SWITCHBOARD_THEME", chosen)
    assert theme.sgr(style) == sgr


def test_both_palettes_have_the_same_colours():
    assert theme.PALETTE["light"].keys() == theme.PALETTE["dark"].keys()
