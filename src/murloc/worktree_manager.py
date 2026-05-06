from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    issue_number: int
    branch: str
    path: Path


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s or "task")[:max_len]


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            cmd,
            output=proc.stdout,
            stderr=proc.stderr,
        )
    return proc


class WorktreeManager:
    def __init__(
        self,
        repo_root: Path,
        worktrees_root: Path,
        base_branch: str = "main",
        push_remote: str = "origin",
    ) -> None:
        self.repo_root = repo_root
        self.worktrees_root = worktrees_root
        self.base_branch = base_branch
        self.push_remote = push_remote

    def branch_name(self, type_: str, issue_number: int, title: str) -> str:
        return f"{type_}/issue-{issue_number}-{_slug(title)}"

    def create(self, type_: str, issue_number: int, title: str) -> Worktree:
        base = self.branch_name(type_, issue_number, title)
        branch = self._unique_remote_branch(base)
        wt_path = self.worktrees_root / f"issue-{issue_number}"
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        self.cleanup(issue_number)
        _run(
            ["git", "worktree", "add", "-B", branch, str(wt_path), self.base_branch],
            cwd=self.repo_root,
        )
        return Worktree(issue_number=issue_number, branch=branch, path=wt_path)

    def _unique_remote_branch(self, base: str) -> str:
        """Pick a branch name not yet present on the push remote.

        Prevents non-fast-forward push rejections when a previous attempt
        on the same issue is still alive on the remote (e.g. as an open
        PR). On the first collision returns ``<base>-2``, then ``-3``, …
        Local branches are always overwritten by ``git worktree add -B``,
        so only the remote needs to be checked.
        """
        if not self._remote_has_branch(base):
            return base
        n = 2
        while self._remote_has_branch(f"{base}-{n}"):
            n += 1
        return f"{base}-{n}"

    def _remote_has_branch(self, branch: str) -> bool:
        try:
            proc = _run(
                ["git", "ls-remote", "--heads", self.push_remote, branch],
                cwd=self.repo_root,
            )
        except subprocess.CalledProcessError:
            # No remote / no network — assume free; push will surface the
            # real error with a clearer stderr than we could fabricate.
            return False
        return bool(proc.stdout.strip())

    def cleanup(self, issue_number: int) -> None:
        """Remove worktree dir and drop it from git's registry.

        Runs unconditionally — git may still have the worktree registered
        even after the directory was deleted out-of-band.
        """
        wt_path = self.worktrees_root / f"issue-{issue_number}"
        with contextlib.suppress(subprocess.CalledProcessError):
            _run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=self.repo_root)
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
        with contextlib.suppress(subprocess.CalledProcessError):
            _run(["git", "worktree", "prune"], cwd=self.repo_root)

    def list_worktrees(self) -> list[Path]:
        if not self.worktrees_root.exists():
            return []
        return [p for p in self.worktrees_root.iterdir() if p.is_dir()]
