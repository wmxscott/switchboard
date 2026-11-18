"""Read-only git lookups. A failing or slow lookup gives None."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

from switchboard import run

WORKERS = 8
STATUS_WORKERS = 32
STATUS_TIMEOUT = 1.0

REV_PARSE = ("rev-parse", "--path-format=absolute", "--git-common-dir")
REFS_FORMAT = "--format=%(HEAD)%09%(refname)%09%(symref)"
STATUS = ("--no-optional-locks", "status", "--porcelain=v2", "--branch")
ORIGIN = ("for-each-ref", "--count=1", "--format=%(refname)", "refs/remotes/origin")
UNPUSHED = ("rev-list", "--count", "HEAD", "--not", "--remotes=origin")

T = TypeVar("T")


@dataclass(frozen=True)
class Worktree:
    root: str
    branch: str
    repo: str


@dataclass(frozen=True)
class Status:
    changed: int
    ahead: int


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


def status(root: str) -> Status | None:
    """Uncommitted changes, and commits not pushed: ahead of the upstream, or for a branch without
    one, not on any origin branch. None past STATUS_TIMEOUT in all."""
    end = time.monotonic() + STATUS_TIMEOUT
    out = _git("-C", root, *STATUS, timeout=STATUS_TIMEOUT)
    if out is None:
        return None
    upstream = [int(line.split()[2]) for line in out if line.startswith("# branch.ab ")]
    ahead = upstream[0] if upstream else _unpushed(root, end)
    changed = sum(not line.startswith("#") for line in out)
    return None if ahead is None else Status(changed, ahead)


def statuses(roots: Iterable[str]) -> dict[str, Status | None]:
    """`status` of each worktree, all at once: the wait is about the slowest one's."""
    return each(status, roots, STATUS_WORKERS)


def _unpushed(root: str, end: float) -> int | None:
    """Commits on no origin branch; 0 when there are no origin branches to compare against."""
    origin = _git("-C", root, *ORIGIN, timeout=end - time.monotonic())
    if not origin:
        return None if origin is None else 0
    counted = _git("-C", root, *UNPUSHED, timeout=end - time.monotonic())
    return int(counted[0]) if counted else None


def repo_name(repo: str) -> str:
    """The folder name of the repo's main worktree or layout root."""
    parent, name = os.path.split(repo)
    if name in (".git", ".bare"):
        return os.path.basename(parent)
    return name.removesuffix(".git")


def each(lookup: Callable[[str], T], keys: Iterable[str], workers: int = WORKERS) -> dict[str, T]:
    """`lookup` run once for each distinct key, in parallel."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as pool:
        return dict(zip(keys, pool.map(lookup, keys), strict=True))


def _git(*args: str, timeout: float | None = None) -> list[str] | None:
    out = run.output("git", *args, timeout=timeout)
    return None if out is None else out.splitlines()
