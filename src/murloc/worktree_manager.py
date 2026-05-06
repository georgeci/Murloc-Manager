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
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


class WorktreeManager:
    def __init__(self, repo_root: Path, worktrees_root: Path, base_branch: str = "main") -> None:
        self.repo_root = repo_root
        self.worktrees_root = worktrees_root
        self.base_branch = base_branch

    def branch_name(self, type_: str, issue_number: int, title: str) -> str:
        return f"{type_}/issue-{issue_number}-{_slug(title)}"

    def create(self, type_: str, issue_number: int, title: str) -> Worktree:
        branch = self.branch_name(type_, issue_number, title)
        wt_path = self.worktrees_root / f"issue-{issue_number}"
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        if wt_path.exists():
            self.cleanup(issue_number)
        _run(
            ["git", "worktree", "add", "-b", branch, str(wt_path), self.base_branch],
            cwd=self.repo_root,
        )
        return Worktree(issue_number=issue_number, branch=branch, path=wt_path)

    def cleanup(self, issue_number: int) -> None:
        wt_path = self.worktrees_root / f"issue-{issue_number}"
        if not wt_path.exists():
            return
        try:
            _run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=self.repo_root)
        except subprocess.CalledProcessError:
            shutil.rmtree(wt_path, ignore_errors=True)
            with contextlib.suppress(subprocess.CalledProcessError):
                _run(["git", "worktree", "prune"], cwd=self.repo_root)

    def list_worktrees(self) -> list[Path]:
        if not self.worktrees_root.exists():
            return []
        return [p for p in self.worktrees_root.iterdir() if p.is_dir()]
