"""The switcher's model: tmux sessions grouped by repo, each with its agents and their state."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from switchboard import git, panestate, projects, tmux
from switchboard.git import Status, Worktree
from switchboard.projects import Label, Project
from switchboard.tmux import Pane, Session


@dataclass(frozen=True)
class Row:
    session: Session
    worktree: Worktree | None
    agents: tuple[Pane, ...] = ()
    status: Status | None = None

    @property
    def state(self) -> str | None:
        return panestate.most_urgent(agent.state for agent in self.agents)


@dataclass(frozen=True)
class Repo:
    path: str
    name: str
    default_branch: str
    rows: tuple[Row, ...]
    label: Label | None = None

    @property
    def title(self) -> str:
        return self.label.title if self.label else self.name

    @property
    def counts(self) -> Counter[str]:
        return Counter(row.state for row in self.rows if row.state)


@dataclass(frozen=True)
class Model:
    repos: tuple[Repo, ...] = ()
    other: tuple[Row, ...] = ()


def load() -> Model:
    sessions = tmux.sessions()
    if not sessions:
        return Model()
    return build(sessions, tmux.panes(), projects.load())


def build(
    sessions: Sequence[Session], panes: Iterable[Pane], project_list: Sequence[Project] = ()
) -> Model:
    agents = tmux.agents_by_session(panes)
    where = {session.name: _where(session) for session in sessions}
    trees = git.each(git.worktree, filter(None, where.values()))
    statuses = git.statuses(tree.root for tree in trees.values() if tree)
    grouped: dict[str, list[Row]] = defaultdict(list)
    other = []
    for session in sessions:
        tree = trees.get(where[session.name])
        status = statuses.get(tree.root) if tree else None
        row = Row(session, tree, agents.get(session.name, ()), status)
        (grouped[tree.repo] if tree else other).append(row)
    defaults = git.each(git.default_branch, grouped)
    labels = projects.labels(project_list, grouped) if project_list and grouped else {}
    repos = []
    for path, rows in grouped.items():
        branch = defaults[path]
        repos.append(
            Repo(path, git.repo_name(path), branch, _ordered(rows, branch), labels.get(path))
        )
    repos.sort(key=lambda repo: (repo.title.casefold(), repo.path))
    other.sort(key=lambda row: row.session.name.casefold())
    return Model(tuple(repos), tuple(other))


def _where(session: Session) -> str:
    path = session.tag or session.path
    return os.path.realpath(path) if os.path.isabs(path) else ""


def _ordered(rows: list[Row], default: str) -> tuple[Row, ...]:
    def key(row: Row) -> tuple[bool, str, str]:
        branch = row.worktree.branch if row.worktree else ""
        return (branch != default, branch.casefold(), row.session.name)

    return tuple(sorted(rows, key=key))
