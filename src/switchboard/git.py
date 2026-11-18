"""Read-only git lookups. A failing or slow lookup gives None."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

from switchboard import run

WORKERS = 8

REV_PARSE = ("rev-parse", "--path-format=absolute", "--git-common-dir")
REFS_FORMAT = "--format=%(HEAD)%09%(refname)%09%(symref)"

T = TypeVar("T")


@dataclass(frozen=True)
class Worktree:
    root: str
    branch: str
    repo: str


def worktree(path: str) -> Worktree | None:
    """The worktree containing `path`. A `.bare` layout's root isn't in one."""
    out = _git("-C", path, *REV_PARSE, "--show-toplevel", "HEAD", "--symbolic-full-name", "HEAD")
    if out is None or len(out) != 4:
        return None
    repo, root, sha, ref = out
    return Worktree(root, sha[:7] if ref == "HEAD" else ref.removeprefix("refs/heads/"), repo)


def common_dir(path: str) -> str | None:
    out = _git("-C", path, *REV_PARSE)
    return out[0] if out and len(out) == 1 else None


def default_branch(repo: str) -> str:
    """Origin's HEAD, else a bare repo's HEAD, else main or master: wkt's rule."""
    out = _git("--git-dir", repo, "for-each-ref", REFS_FORMAT, "refs/heads", "refs/remotes/origin")
    refs, head = {}, ""
    for line in out or ():
        star, name, target = line.split("\t")
        refs[name] = target
        head = name if star == "*" else head
    origin = refs.get("refs/remotes/origin/HEAD", "")
    if origin.startswith("refs/remotes/origin/"):
        return origin.removeprefix("refs/remotes/origin/")
    if head and _git("--git-dir", repo, "rev-parse", "--is-bare-repository") == ["true"]:
        return head.removeprefix("refs/heads/")
    for name in ("main", "master"):
        if f"refs/remotes/origin/{name}" in refs or f"refs/heads/{name}" in refs:
            return name
    return "main"


def repo_name(repo: str) -> str:
    """The folder name of the repo's main worktree or layout root."""
    parent, name = os.path.split(repo)
    if name in (".git", ".bare"):
        return os.path.basename(parent)
    return name.removesuffix(".git")


def each(lookup: Callable[[str], T], keys: Iterable[str]) -> dict[str, T]:
    """`lookup` run once for each distinct key, in parallel."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(keys))) as pool:
        return dict(zip(keys, pool.map(lookup, keys), strict=True))


def _git(*args: str) -> list[str] | None:
    out = run.output("git", *args)
    return None if out is None else out.splitlines()
