"""The picker's colours, as in wkt's picker: Catppuccin Latte in light mode and Macchiato in dark
mode. `$SWITCHBOARD_THEME` chooses if it's `light` or `dark`, else theme-monitor's trigger file,
else macOS's own setting, else light."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from switchboard import run

ENV = "SWITCHBOARD_THEME"
THEMES = ("light", "dark")
TRIGGER = ("theme-monitor", "theme-change.trigger")

PALETTE = {
    "light": {
        "overlay0": "156;160;176",
        "overlay1": "140;143;161",
        "subtext0": "108;111;133",
        "text": "76;79;105",
        "green": "64;160;43",
        "red": "210;15;57",
        "peach": "254;100;11",
    },
    "dark": {
        "overlay0": "110;115;141",
        "overlay1": "128;135;162",
        "subtext0": "165;173;203",
        "text": "202;211;245",
        "green": "166;218;149",
        "red": "237;135;150",
        "peach": "245;169;127",
    },
}
ATTRS = {"bold": "1", "dim": "2"}


def detect() -> str:
    chosen = os.environ.get(ENV, "").lower()
    if chosen in THEMES:
        return chosen
    data = os.environ.get("XDG_DATA_HOME", "")
    if not data.startswith("/"):
        data = os.path.expanduser("~/.local/share")
    try:
        found = "".join(Path(data, *TRIGGER).read_text(encoding="utf-8").split())
    except (OSError, UnicodeDecodeError):
        found = ""
    if found in THEMES:
        return found
    if sys.platform == "darwin":
        style = run.output("defaults", "read", "-g", "AppleInterfaceStyle") or ""
        return "dark" if style.strip() == "Dark" else "light"
    return "light"


def sgr(style: str) -> str:
    """The SGR parameters for `style`: a palette colour after any of `bold` and `dim`. Outside the
    picker, which exports its theme, each call detects one."""
    *attrs, colour = style.split()
    theme = os.environ.get(ENV, "")
    rgb = PALETTE[theme if theme in THEMES else detect()][colour]
    return ";".join([*(ATTRS[attr] for attr in attrs), f"38;2;{rgb}"])
