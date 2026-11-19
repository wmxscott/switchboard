from __future__ import annotations

import itertools
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRUBBED = ("TMUX", "CLAUDECODE")
SCRUBBED_PREFIXES = ("TMUX_", "SWITCHBOARD_", "CLAUDE_")

# A stand-in for `tmux`, and for `afplay`. It logs every call and answers from a JSON spec keyed by
# the whole command line joined by spaces, else by subcommand, "*" matching any other:
# {"list-sessions": {"code": 0, "stdout": "...", "stderr": ""}}. A command without an answer
# succeeds with no output.
STUB_TMUX = """#!{python}
import json, sys

args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(json.dumps({{"args": args}}) + "\\n")
try:
    with open({spec!r}) as f:
        spec = json.load(f)
except (OSError, ValueError):
    spec = {{}}
answer = spec.get(" ".join(args), spec.get(args[0] if args else "", spec.get("*", {{}})))
sys.stdout.write(answer.get("stdout", ""))
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer.get("code", 0))
"""

# A stand-in for `fzf`. Call n logs its arguments and stdin, then replays the
# spec's reply n: {"replies": [{"code": 0, "stdout": "..."}]}. A call without a
# reply fails with 98.
STUB_FZF = """#!{python}
import json, sys

args = sys.argv[1:]
try:
    with open({log!r}) as log:
        n = sum(1 for _ in log)
except OSError:
    n = 0
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
with open({log!r}, "a") as log:
    log.write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
try:
    with open({spec!r}) as f:
        replies = json.load(f).get("replies", [])
except (OSError, ValueError):
    replies = []
if n >= len(replies):
    sys.stderr.write(f"stub fzf: no reply for call {{n + 1}}\\n")
    sys.exit(98)
sys.stdout.write(replies[n].get("stdout", ""))
sys.exit(replies[n].get("code", 0))
"""


@dataclass
class Stub:
    spec_path: Path
    log_path: Path

    def spec(self) -> dict:
        return json.loads(self.spec_path.read_text()) if self.spec_path.exists() else {}

    def entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]


class StubTmux(Stub):
    def answer(self, command: str, stdout: str = "", stderr: str = "", code: int = 0) -> None:
        """How the stub answers `command`, a subcommand or a whole command line, or with "*", any
        command without its own answer."""
        spec = self.spec()
        spec[command] = {"code": code, "stdout": stdout, "stderr": stderr}
        self.spec_path.write_text(json.dumps(spec))

    def calls(self) -> list[list[str]]:
        return [entry["args"] for entry in self.entries()]


class StubFzf(Stub):
    def reply(self, stdout: str = "", code: int = 0) -> None:
        """What the next call without a reply prints, and its exit code."""
        spec = self.spec()
        spec.setdefault("replies", []).append({"code": code, "stdout": stdout})
        self.spec_path.write_text(json.dumps(spec))

    def calls(self) -> list[dict]:
        """Each call's `args` and `stdin`."""
        return self.entries()


@dataclass
class Stubs:
    tmux: StubTmux
    fzf: StubFzf
    afplay: StubTmux


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Stubs:
    """Every test gets its own HOME and XDG dirs, and stub `tmux`, `fzf` and `afplay` first on
    PATH."""
    for var in list(os.environ):
        if var in SCRUBBED or var.startswith(SCRUBBED_PREFIXES):
            monkeypatch.delenv(var)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = Stubs(
        tmux=StubTmux(tmp_path / "tmux-spec.json", tmp_path / "tmux-log.jsonl"),
        fzf=StubFzf(tmp_path / "fzf-spec.json", tmp_path / "fzf-log.jsonl"),
        afplay=StubTmux(tmp_path / "afplay-spec.json", tmp_path / "afplay-log.jsonl"),
    )
    for name, source, stub in (
        ("tmux", STUB_TMUX, stubs.tmux),
        ("fzf", STUB_FZF, stubs.fzf),
        ("afplay", STUB_TMUX, stubs.afplay),
    ):
        path = bin_dir / name
        path.write_text(
            source.format(python=sys.executable, log=str(stub.log_path), spec=str(stub.spec_path))
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    for name in ("tmux", "fzf", "afplay"):
        if shutil.which(name) != str(bin_dir / name):
            pytest.fail(f"refusing to run: {name} doesn't resolve to the stub", pytrace=False)
    return stubs


@pytest.fixture
def stubs(isolated: Stubs) -> Stubs:
    return isolated


def git(*args: str | Path) -> str:
    result = subprocess.run(["git", *map(str, args)], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def real(path: str | Path) -> str:
    return os.path.realpath(path)


@dataclass
class Repos:
    """Real git repositories under a temporary folder."""

    root: Path

    def origin(self, name: str, default: str = "main", branches: tuple[str, ...] = ()) -> Path:
        path = self.root / "origins" / name
        git("init", "-q", "-b", default, path)
        git("-C", path, "commit", "-q", "--allow-empty", "-m", "init")
        for branch in branches:
            git("-C", path, "branch", branch)
        return path

    def clone(self, origin: Path, name: str) -> Path:
        git("clone", "-q", origin, self.root / name)
        return self.root / name

    def layout(self, origin: Path, name: str, *worktrees: str) -> Path:
        """A `.bare` layout, as `wkt setup` makes, with a worktree for each branch."""
        root = self.root / name
        git("clone", "-q", "--bare", origin, root / ".bare")
        (root / ".git").write_text("gitdir: ./.bare\n")
        for branch in worktrees:
            git("-C", root, "worktree", "add", "-q", branch, branch)
        return root

    def slow(self, path: Path, seconds: int = 3) -> None:
        """Makes `git status` in `path` take `seconds`, through an fsmonitor hook that sleeps."""
        hook = self.root / f"{path.name}-fsmonitor"
        hook.write_text(f"#!/bin/sh\nsleep {seconds}\n")
        hook.chmod(0o755)
        git("-C", path, "config", "core.fsmonitor", hook)

    def commit(self, path: Path, count: int = 1) -> None:
        for n in range(count):
            git("-C", path, "commit", "-q", "--allow-empty", "-m", f"commit {n}")


@pytest.fixture
def repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repos:
    for var in list(os.environ):
        if var.startswith("GIT_"):
            monkeypatch.delenv(var)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
    (tmp_path / "repos").mkdir()
    return Repos(tmp_path / "repos")


@pytest.fixture
def ps(tmp_path):
    """A stub `ps` first on PATH. `ancestors(...)` lists them as this process's parents, nearest
    first, with an unrelated process 999 beside them."""
    out, log, path = tmp_path / "ps-out", tmp_path / "ps-log", tmp_path / "bin" / "ps"

    def ancestors(*pids: int, code: int = 0) -> None:
        chain = [os.getpid(), *pids, 1, 0]
        rows = [*itertools.pairwise(chain), (999, 1)]
        out.write_text("".join(f"{pid:>6} {parent:>6}\n" for pid, parent in rows))
        path.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\ncat "{out}"\nexit {code}\n')
        path.chmod(0o755)

    def calls() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    ancestors(500, 400)
    return SimpleNamespace(ancestors=ancestors, calls=calls)
