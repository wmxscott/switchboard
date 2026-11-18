"""Worktree and default-branch lookups, against real git repositories."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import git, real

from switchboard.git import (
    Status,
    Worktree,
    common_dir,
    default_branch,
    each,
    repo_name,
    status,
    statuses,
    worktree,
)


def test_a_normal_clone(repos):
    clone = repos.clone(repos.origin("widget", branches=("feat",)), "widget")
    (clone / "src").mkdir()
    expected = Worktree(real(clone), "main", real(clone / ".git"))
    assert worktree(str(clone)) == expected
    assert worktree(str(clone / "src")) == expected
    assert common_dir(str(clone)) == real(clone / ".git")


def test_a_bare_layout(repos):
    root = repos.layout(repos.origin("widget", branches=("feat",)), "widget", "main", "feat")
    bare = real(root / ".bare")
    assert worktree(str(root / "feat")) == Worktree(real(root / "feat"), "feat", bare)
    assert worktree(str(root / "main")) == Worktree(real(root / "main"), "main", bare)
    assert worktree(str(root)) is None
    assert worktree(str(root / ".bare")) is None
    assert common_dir(str(root)) == bare
    assert common_dir(str(root / "feat")) == bare


def test_a_detached_worktree_shows_its_short_sha(repos):
    root = repos.layout(repos.origin("widget"), "widget", "main")
    git("-C", root, "worktree", "add", "-q", "--detach", "spike", "main")
    sha = git("-C", root / "spike", "rev-parse", "HEAD")
    assert worktree(str(root / "spike")) == Worktree(
        real(root / "spike"), sha[:7], real(root / ".bare")
    )


def test_outside_git(tmp_path):
    assert worktree(str(tmp_path)) is None
    assert worktree(str(tmp_path / "missing")) is None
    assert common_dir(str(tmp_path)) is None


def test_default_branch_is_origins_head(repos):
    clone = repos.clone(repos.origin("widget", default="trunk", branches=("main",)), "widget")
    git("-C", clone, "switch", "-q", "main")
    assert default_branch(real(clone / ".git")) == "trunk"


def test_default_branch_is_a_bare_repos_head_without_origins_head(repos):
    root = repos.layout(repos.origin("widget", default="trunk", branches=("main",)), "widget")
    assert git("--git-dir", root / ".bare", "for-each-ref", "refs/remotes") == ""
    assert default_branch(real(root / ".bare")) == "trunk"


@pytest.mark.parametrize(("branches", "default"), [(("master",), "master"), (("dev",), "main")])
def test_default_branch_falls_back_to_main_or_master(repos, branches, default):
    path = repos.origin("widget", default="feat", branches=branches)
    assert default_branch(real(path / ".git")) == default


def test_default_branch_of_a_broken_repo_is_main(tmp_path):
    assert default_branch(str(tmp_path)) == "main"


@pytest.mark.parametrize(
    ("common", "name"),
    [("/r/widget/.git", "widget"), ("/r/widget/.bare", "widget"), ("/r/widget.git", "widget")],
)
def test_repo_name(common, name):
    assert repo_name(common) == name


def test_each_runs_a_lookup_once_per_distinct_key():
    seen = []
    assert each(lambda key: seen.append(key) or key.upper(), ["a", "b", "a"]) == {
        "a": "A",
        "b": "B",
    }
    assert sorted(seen) == ["a", "b"]
    assert each(str.upper, []) == {}


def test_status_of_a_clean_pushed_clone(repos):
    assert status(str(repos.clone(repos.origin("widget"), "widget"))) == Status(0, 0)


def test_status_counts_the_lines_of_git_status_porcelain(repos):
    clone = repos.clone(repos.origin("widget"), "widget")
    (clone / "untracked").write_text("a")
    (clone / "staged").write_text("b")
    git("-C", clone, "add", "staged")
    (clone / "folder").mkdir()
    (clone / "folder/inside").write_text("c")
    assert status(str(clone)) == Status(3, 0)
    assert len(git("-C", clone, "status", "--porcelain").splitlines()) == 3


def test_status_counts_commits_ahead_of_the_upstream(repos):
    clone = repos.clone(repos.origin("widget"), "widget")
    repos.commit(clone, 2)
    (clone / "new").write_text("a")
    assert status(str(clone)) == Status(1, 2)


def test_ahead_is_against_the_upstream_even_when_another_origin_branch_has_the_commits(repos):
    origin = repos.origin("widget", branches=("feat",))
    repos.commit(origin)
    clone = repos.clone(origin, "widget")
    git("-C", clone, "switch", "-q", "feat")
    git("-C", clone, "merge", "-q", "--ff-only", "origin/main")
    assert status(str(clone)) == Status(0, 1)


def test_without_an_upstream_ahead_is_the_commits_on_no_origin_branch(repos):
    clone = repos.clone(repos.origin("widget"), "widget")
    git("-C", clone, "switch", "-q", "-c", "topic")
    assert git("-C", clone, "for-each-ref", "--format=%(upstream)", "refs/heads/topic") == ""
    assert status(str(clone)) == Status(0, 0)
    repos.commit(clone, 3)
    assert status(str(clone)) == Status(0, 3)


def test_without_any_origin_branches_there_is_no_ahead(repos):
    alone = repos.origin("alone")
    repos.commit(alone, 2)
    (alone / "new").write_text("a")
    assert git("-C", alone, "remote") == ""
    assert status(str(alone)) == Status(1, 0)
    unfetched = repos.origin("unfetched")
    git("-C", unfetched, "remote", "add", "origin", alone)
    assert git("-C", unfetched, "for-each-ref", "refs/remotes/origin") == ""
    assert status(str(unfetched)) == Status(0, 0)


def test_a_slow_status_gives_none_at_the_timeout(repos, monkeypatch):
    monkeypatch.setattr("switchboard.git.STATUS_TIMEOUT", 0.3)
    clone = repos.clone(repos.origin("widget"), "widget")
    repos.slow(clone)
    started = time.monotonic()
    assert status(str(clone)) is None
    assert time.monotonic() - started < 1.5


def test_a_failing_status_gives_none(repos, tmp_path):
    clone = repos.clone(repos.origin("widget"), "widget")
    (clone / ".git/index").write_text("not an index")
    assert worktree(str(clone)) is not None
    assert status(str(clone)) is None
    assert status(str(tmp_path)) is None


def test_statuses_run_at_once_so_slow_ones_cost_one_timeout(repos, monkeypatch):
    monkeypatch.setattr("switchboard.git.STATUS_TIMEOUT", 0.5)
    origin = repos.origin("widget")
    clones = [str(repos.clone(origin, f"w{n}")) for n in range(5)]
    for clone in clones[1:]:
        repos.slow(Path(clone))
    started = time.monotonic()
    found = statuses(clones)
    assert time.monotonic() - started < 1.5
    assert found == {clones[0]: Status(0, 0)} | dict.fromkeys(clones[1:])
