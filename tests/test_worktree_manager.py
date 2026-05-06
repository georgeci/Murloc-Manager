from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murloc.worktree_manager import WorktreeManager, _slug


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README.md").write_text("hi")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    return repo


def test_slug_basic() -> None:
    assert _slug("Add Foo Bar!") == "add-foo-bar"
    assert _slug("") == "task"


def test_create_and_cleanup(repo: Path, tmp_path: Path) -> None:
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    wt = wm.create(42, "Fix typo in README")
    assert wt.path.exists()
    assert wt.branch == "murloc/issue-42-fix-typo-in-readme"
    assert (wt.path / "README.md").exists()

    wm.cleanup(42)
    assert not wt.path.exists()


def test_create_when_path_exists_recreates(repo: Path, tmp_path: Path) -> None:
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    wm.create(1, "First")
    # Issue with same number — should cleanup and recreate
    wt2 = wm.create(1, "Second attempt")
    assert wt2.path.exists()
    wm.cleanup(1)
