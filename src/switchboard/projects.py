"""Repo labels from Herdr's project list. A missing or invalid list means no labels."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from switchboard import git

RELATIVE_PATH = "herdr/plugins/config/herdr-projects/projects.toml"


@dataclass(frozen=True)
class Label:
    icon: str
    title: str

    def __str__(self) -> str:
        return f"{self.icon} {self.title}" if self.icon else self.title


@dataclass(frozen=True)
class Project:
    path: str
    label: Label


def load(path: Path | None = None) -> list[Project]:
    """The list's projects, leaving out any entry without a name or an absolute path."""
    try:
        path = path or Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config", RELATIVE_PATH)
        data = tomllib.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    icons = {_str(g, "name"): _str(g, "icon") for g in _tables(data, "groups") if _str(g, "name")}
    projects = []
    for entry in _tables(data, "projects"):
        name, group = _str(entry, "name"), _str(entry, "group")
        where = os.path.expanduser(_str(entry, "path"))
        if name and os.path.isabs(where):
            icon = _str(entry, "icon") or icons.get(group, "")
            projects.append(Project(where, Label(icon, f"{group}/{name}" if group else name)))
    return projects


def labels(projects: Sequence[Project], repos: Collection[str]) -> dict[str, Label]:
    """Each repo's label, from the first project whose path has the same git common dir."""
    found = git.each(git.common_dir, (project.path for project in projects))
    result: dict[str, Label] = {}
    for project in projects:
        repo = found[project.path]
        if repo in repos:
            result.setdefault(repo, project.label)
    return result


def _tables(data: dict, key: str) -> list[dict]:
    value = data.get(key)
    return [table for table in value if isinstance(table, dict)] if isinstance(value, list) else []


def _str(table: dict, key: str) -> str:
    value = table.get(key)
    return value.strip() if isinstance(value, str) else ""
