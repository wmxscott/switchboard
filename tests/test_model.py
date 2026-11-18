"""The switcher's model, from the stub tmux's answers and real git repositories."""

from __future__ import annotations

import os
from pathlib import Path

from conftest import git, real

from switchboard import model
from switchboard.git import Status, Worktree
from switchboard.projects import Label, Project
from switchboard.tmux import Pane, Session


def sessions_text(*rows: tuple[str, str, str | Path]) -> str:
    return "".join(f"{name}\t{tag}\t{path}\t0\t\n" for name, tag, path in rows)


def panes_text(*rows: tuple[str, str, str, str]) -> str:
    """Each row is a session, a role, a turn and the pending keys."""
    return "".join(
        f"{session}\t0\t%{n}\tclaude\t{role}\t{turn}\t{pending}\t0\t\n"
        for n, (session, role, turn, pending) in enumerate(rows)
    )


def layout_and_clone(repos):
    widget = repos.layout(
        repos.origin("widget", branches=("alpha", "feat", "zed")),
        "widget",
        "main",
        "alpha",
        "feat",
        "zed",
    )
    gadget = repos.clone(repos.origin("gadget"), "gadget")
    return widget, gadget


def shape(found: model.Model) -> list[tuple[str, list[tuple[str, str]]]]:
    groups = [(repo.title, repo.rows) for repo in found.repos] + [("other", found.other)]
    return [
        (title, [(row.session.name, row.worktree.branch if row.worktree else "") for row in rows])
        for title, rows in groups
    ]


def test_sessions_resolve_to_worktrees_grouped_by_repo(stubs, repos, tmp_path):
    widget, gadget = layout_and_clone(repos)
    (widget / "main/src").mkdir()
    os.symlink(gadget, tmp_path / "link")
    stubs.tmux.answer(
        "list-sessions",
        stdout=sessions_text(
            ("widget/zed", "", widget / "zed"),
            ("home", "", Path.home()),
            ("widget/feat", widget / "feat", Path.home()),
            ("gadget", "", tmp_path / "link"),
            ("widget/main", "", widget / "main/src"),
            ("widget/alpha", "", widget / "alpha"),
            ("widget", "", widget),
            ("gone", "", tmp_path / "gone"),
        ),
    )
    found = model.load()
    assert shape(found) == [
        ("gadget", [("gadget", "main")]),
        (
            "widget",
            [
                ("widget/main", "main"),
                ("widget/alpha", "alpha"),
                ("widget/feat", "feat"),
                ("widget/zed", "zed"),
            ],
        ),
        ("other", [("gone", ""), ("home", ""), ("widget", "")]),
    ]
    gadget_repo, widget_repo = found.repos
    assert (gadget_repo.path, gadget_repo.name) == (real(gadget / ".git"), "gadget")
    assert (widget_repo.path, widget_repo.name) == (real(widget / ".bare"), "widget")
    assert gadget_repo.rows[0].worktree == Worktree(real(gadget), "main", real(gadget / ".git"))
    assert widget_repo.rows[2].worktree.root == real(widget / "feat")
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions", "list-panes"]


def test_the_default_branch_comes_first(stubs, repos):
    origin = repos.origin("widget", default="trunk", branches=("alpha", "zed"))
    widget = repos.layout(origin, "widget", "zed", "trunk", "alpha")
    stubs.tmux.answer(
        "list-sessions",
        stdout=sessions_text(*((f"w/{b}", "", widget / b) for b in ("zed", "trunk", "alpha"))),
    )
    (repo,) = model.load().repos
    assert repo.default_branch == "trunk"
    assert [row.session.name for row in repo.rows] == ["w/trunk", "w/alpha", "w/zed"]


def test_a_detached_worktree_shows_its_short_sha(stubs, repos):
    widget, _ = layout_and_clone(repos)
    git("-C", widget, "worktree", "add", "-q", "--detach", "spike", "main")
    sha = git("-C", widget / "spike", "rev-parse", "HEAD")[:7]
    stubs.tmux.answer(
        "list-sessions",
        stdout=sessions_text(("w/spike", "", widget / "spike"), ("w/main", "", widget / "main")),
    )
    (repo,) = model.load().repos
    assert [(row.session.name, row.worktree.branch) for row in repo.rows] == [
        ("w/main", "main"),
        ("w/spike", sha),
    ]


def test_repos_sort_by_label_title_ignoring_the_icon(repos):
    widget, gadget = layout_and_clone(repos)
    sessions = [Session("g", "", str(gadget)), Session("w", "", str(widget / "main"))]
    labelled = [Project(str(widget), Label("!", "a-tools/widget"))]
    found = model.build(sessions, [], labelled)
    assert [str(repo.label or repo.title) for repo in found.repos] == ["! a-tools/widget", "gadget"]
    assert [repo.title for repo in model.build(sessions, []).repos] == ["gadget", "widget"]


def test_load_reads_the_project_list(stubs, repos):
    widget, _ = layout_and_clone(repos)
    path = Path.home() / ".config/herdr/plugins/config/herdr-projects/projects.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f"[[projects]]\nname = 'widget'\nicon = 'W'\npath = '{widget}'\n")
    stubs.tmux.answer("list-sessions", stdout=sessions_text(("w", "", widget / "main")))
    (repo,) = model.load().repos
    assert repo.label == Label("W", "widget")


def test_rows_carry_their_agents_and_most_urgent_state(stubs, repos):
    widget, _ = layout_and_clone(repos)
    stubs.tmux.answer(
        "list-sessions",
        stdout=sessions_text(
            *((f"w/{b}", "", widget / b) for b in ("main", "alpha", "feat", "zed")),
            ("scratch", "", Path.home()),
        ),
    )
    stubs.tmux.answer(
        "list-panes",
        stdout=panes_text(
            ("w/main", "lead", "done", ""),
            ("w/main", "teammate", "idle", "lead"),
            ("w/main", "", "", ""),
            ("w/alpha", "lead", "working", ""),
            ("w/alpha", "teammate", "done", ""),
            ("w/feat", "lead", "idle", ""),
            ("w/feat", "", "done", "lead"),
            ("scratch", "lead", "working", ""),
        ),
    )
    found = model.load()
    (repo,) = found.repos
    rows = {row.session.name: row for row in (*repo.rows, *found.other)}
    assert {name: row.state for name, row in rows.items()} == {
        "w/main": "needs",
        "w/alpha": "done",
        "w/feat": "idle",
        "w/zed": None,
        "scratch": "working",
    }
    assert [agent.id for agent in rows["w/main"].agents] == ["%0", "%1"]
    assert rows["w/zed"].agents == ()
    assert repo.counts == {"needs": 1, "done": 1, "idle": 1}


def test_rows_carry_git_status_and_a_slow_or_failing_lookup_leaves_its_row_without(
    stubs, repos, monkeypatch
):
    monkeypatch.setattr("switchboard.git.STATUS_TIMEOUT", 0.3)
    origin = repos.origin("widget")
    names = ("clean", "dirty", "ahead", "slow", "broken")
    paths = [repos.clone(origin, name) for name in names]
    _, dirty, ahead, slow, broken = paths
    (dirty / "new").write_text("a")
    repos.commit(ahead, 2)
    repos.slow(slow)
    (broken / ".git/index").write_text("not an index")
    stubs.tmux.answer("list-sessions", stdout=sessions_text(*((p.name, "", p) for p in paths)))
    found = model.load()
    assert {row.session.name: row.status for repo in found.repos for row in repo.rows} == {
        "clean": Status(0, 0),
        "dirty": Status(1, 0),
        "ahead": Status(0, 2),
        "slow": None,
        "broken": None,
    }
    assert all(row.worktree for repo in found.repos for row in repo.rows)


def test_no_server_is_an_empty_model(stubs):
    stubs.tmux.answer("*", code=1, stderr="no server running on /tmp/tmux-0/default\n")
    assert model.load() == model.Model()
    assert [call[0] for call in stubs.tmux.calls()] == ["list-sessions"]


def test_build_without_git():
    session = Session("s", "", "relative/path")
    agent = Pane("s", 1, "%4", "claude", "lead", "done")
    found = model.build([session], [agent])
    assert found == model.Model((), (model.Row(session, None, (agent,)),))
