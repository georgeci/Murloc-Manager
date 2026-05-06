from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from murloc.executors.base import ExecResult
from murloc.github_client import IssueRef
from murloc.orchestrator import Orchestrator
from murloc.retry_policy import RetryPolicy
from murloc.worktree_manager import WorktreeManager


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@dataclass
class FakeGh:
    claimed: list[int] = field(default_factory=list)
    review: list[tuple[int, str, str]] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)
    prs_opened: list[tuple[int, str]] = field(default_factory=list)

    def claim(self, issue_number: int) -> bool:
        self.claimed.append(issue_number)
        return True

    def mark_review(self, issue_number: int, pr_url: str, summary: str) -> None:
        self.review.append((issue_number, pr_url, summary))

    def mark_failed(self, issue_number: int, summary: str) -> None:
        self.failed.append((issue_number, summary))

    def open_pr(self, issue_number: int, branch: str, title: str, body: str) -> str:
        self.prs_opened.append((issue_number, branch))
        return f"https://example.test/pr/{issue_number}"


class FakeExecutor:
    """Writes a file in cwd to simulate the agent making a change."""

    def __init__(self, contents: str = "agent was here\n", ok: bool = True) -> None:
        self.contents = contents
        self.ok = ok
        self.calls = 0

    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult:
        self.calls += 1
        if not self.ok:
            return ExecResult(ok=False, stdout="", stderr="boom", exit_code=2)
        (cwd / "AGENT.txt").write_text(f"{self.contents} attempt={self.calls}\n")
        # Stage so the next git push has something to push.
        subprocess.run(
            ["git", "add", "AGENT.txt"], cwd=str(cwd), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "agent change"],
            cwd=str(cwd), check=True, capture_output=True,
        )
        return ExecResult(ok=True, stdout="", stderr="", exit_code=0)


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "README.md").write_text("hi")
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-u", "origin", "main"], repo)
    return repo, remote


def test_orchestrator_happy_path(repo_with_remote: tuple[Path, Path], tmp_path: Path) -> None:
    repo, remote = repo_with_remote
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    gh = FakeGh()
    executor = FakeExecutor()
    orch = Orchestrator(
        gh=gh,
        worktrees=wm,
        executor=executor,
        retry=RetryPolicy(max_attempts=3),
        check_commands=[["true"]],
        executor_timeout_sec=60,
    )

    issue = IssueRef(number=7, title="Add agent file", body="please", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is True
    assert outcome.attempts == 1
    assert outcome.pr_url == "https://example.test/pr/7"
    assert gh.claimed == [7]
    assert len(gh.review) == 1
    assert gh.failed == []
    assert executor.calls == 1


def test_orchestrator_failed_after_max_attempts(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    gh = FakeGh()
    executor = FakeExecutor()
    orch = Orchestrator(
        gh=gh,
        worktrees=wm,
        executor=executor,
        retry=RetryPolicy(max_attempts=2),
        check_commands=[["false"]],
        executor_timeout_sec=60,
    )

    issue = IssueRef(number=8, title="Will fail", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is False
    assert outcome.attempts == 2
    assert gh.failed and gh.failed[0][0] == 8
    assert gh.review == []
    assert executor.calls == 2


def test_orchestrator_executor_failure_marks_failed(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    gh = FakeGh()
    executor = FakeExecutor(ok=False)
    orch = Orchestrator(
        gh=gh,
        worktrees=wm,
        executor=executor,
        retry=RetryPolicy(max_attempts=2),
        check_commands=[["true"]],  # checks would pass, but executor fails first
        executor_timeout_sec=60,
    )

    issue = IssueRef(number=9, title="Executor dies", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is False
    assert outcome.attempts == 2
    assert gh.review == []
    assert gh.failed and "executor:FakeExecutor" in gh.failed[0][1]
    assert "boom" in gh.failed[0][1]
