"""Worktree and default-branch lookups, against real git repositories."""

from __future__ import annotations

import pytest
from conftest import git, real

from switchboard.git import Worktree, common_dir, default_branch, each, repo_name, worktree


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
