"""Reading switchboard's config and labelling repos with it."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import real

from switchboard import projects
from switchboard.projects import Label, Project


def write_list(text: str) -> Path:
    path = Path.home() / ".config/switchboard/config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_projects_icon_wins_over_its_groups():
    write_list(
        """
        [[groups]]
        name = "tools"
        icon = "T"

        [[projects]]
        name = "widget"
        group = "tools"
        path = "~/widget"

        [[projects]]
        name = "gadget"
        group = "tools"
        icon = "G"
        path = "/srv/gadget"

        [[projects]]
        name = "loose"
        icon = "L"
        path = "~/loose"

        [[projects]]
        name = "plain"
        group = "nogroup"
        path = "~/plain"
        """
    )
    home = str(Path.home())
    found = projects.load()
    assert found == [
        Project(f"{home}/widget", Label("T", "tools/widget")),
        Project("/srv/gadget", Label("G", "tools/gadget")),
        Project(f"{home}/loose", Label("L", "loose")),
        Project(f"{home}/plain", Label("", "nogroup/plain")),
    ]
    assert [str(project.label) for project in found] == [
        "T tools/widget",
        "G tools/gadget",
        "L loose",
        "nogroup/plain",
    ]


def test_bad_entries_are_left_out():
    write_list(
        """
        groups = [{ name = 3, icon = "X" }, "not a table", { icon = "Y" }]

        [[projects]]
        name = "fine"
        path = "/srv/fine"
        icon = 7

        [[projects]]
        path = "/srv/nameless"

        [[projects]]
        name = "relative"
        path = "srv/relative"

        [[projects]]
        name = "pathless"

        [[projects]]
        name = ["not", "a", "string"]
        path = "/srv/list"
        """
    )
    assert projects.load() == [Project("/srv/fine", Label("", "fine"))]


@pytest.mark.parametrize(
    "text", ["projects = [", "projects = 'not a list'", "[[projects]]\nname = 'x'\nname = 'y'\n"]
)
def test_an_invalid_list_means_no_projects(text):
    write_list(text)
    assert projects.load() == []


def test_a_missing_list_means_no_projects():
    assert projects.load() == []


def test_a_list_that_is_not_utf8_means_no_projects():
    write_list("").write_bytes(b"\xff\xfe[[projects]]\n")
    assert projects.load() == []


def test_xdg_config_home_moves_the_list(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "elsewhere"))
    write_list("[[projects]]\nname = 'ignored'\npath = '/srv/ignored'\n")
    assert projects.load() == []
    path = tmp_path / "elsewhere/switchboard/config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[[projects]]\nname = 'moved'\npath = '/srv/moved'\n")
    assert projects.load() == [Project("/srv/moved", Label("", "moved"))]


def test_a_project_labels_the_repo_with_its_common_dir(repos):
    layout = repos.layout(repos.origin("widget", branches=("feat",)), "widget", "main", "feat")
    clone = repos.clone(repos.origin("gadget"), "gadget")
    found = [
        Project(str(layout), Label("W", "widget")),
        Project(str(layout / "feat"), Label("X", "second")),
        Project(str(clone / "sub/missing"), Label("M", "missing")),
        Project(str(clone), Label("G", "gadget")),
        Project(str(repos.root / "nowhere"), Label("N", "nowhere")),
    ]
    widget, gadget = real(layout / ".bare"), real(clone / ".git")
    assert projects.labels(found, {widget, gadget}) == {
        widget: Label("W", "widget"),
        gadget: Label("G", "gadget"),
    }
    assert projects.labels(found, {widget}) == {widget: Label("W", "widget")}
