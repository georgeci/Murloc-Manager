from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from murloc.executors.base import ExecResult
from murloc.github_client import IssueRef
from murloc.orchestrator import Orchestrator
from murloc.worktree_manager import WorktreeManager


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@dataclass
class FakeGh:
    claimed: list[int] = field(default_factory=list)
    review: list[tuple[int, str, str]] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)
    prs_opened: list[tuple[int, str, str, str]] = field(default_factory=list)

    def claim(self, issue_number: int) -> bool:
        self.claimed.append(issue_number)
        return True

    def mark_review(self, issue_number: int, pr_url: str, summary: str) -> None:
        self.review.append((issue_number, pr_url, summary))

    def mark_failed(self, issue_number: int, summary: str) -> None:
        self.failed.append((issue_number, summary))

    def open_pr(self, issue_number: int, branch: str, title: str, body: str) -> str:
        self.prs_opened.append((issue_number, branch, title, body))
        return f"https://example.test/pr/{issue_number}"


class FakeExecutor:
    """Simulates the agent: edits a file and creates a commit with a PR-style message."""

    def __init__(
        self,
        commit_subject: str = "feat: add agent file",
        commit_body: str = "Adds AGENT.txt with a marker so we can ship.",
        ok: bool = True,
        commit: bool = True,
    ) -> None:
        self.commit_subject = commit_subject
        self.commit_body = commit_body
        self.ok = ok
        self.commit = commit
        self.calls = 0

    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult:
        self.calls += 1
        if not self.ok:
            return ExecResult(ok=False, stdout="", stderr="boom", exit_code=2)
        if self.commit:
            (cwd / "AGENT.txt").write_text(f"agent was here attempt={self.calls}\n")
            subprocess.run(
                ["git", "add", "AGENT.txt"], cwd=str(cwd), check=True, capture_output=True
            )
            msg = self.commit_subject
            if self.commit_body:
                msg = f"{self.commit_subject}\n\n{self.commit_body}"
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", msg],
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


def _make_orch(repo: Path, tmp_path: Path, gh: FakeGh, executor: FakeExecutor) -> Orchestrator:
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    return Orchestrator(gh=gh, worktrees=wm, executor=executor, executor_timeout_sec=60)


def test_happy_path_uses_first_commit_for_pr(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    gh = FakeGh()
    executor = FakeExecutor(
        commit_subject="feat: add agent file",
        commit_body="Adds AGENT.txt with a marker so we can ship.",
    )
    orch = _make_orch(repo, tmp_path, gh, executor)

    issue = IssueRef(
        number=7, title="anything", body="please", labels=["type:feat"], html_url="x"
    )
    outcome = orch.process(issue)

    assert outcome.success is True
    assert outcome.pr_url == "https://example.test/pr/7"
    assert gh.claimed == [7]
    assert len(gh.review) == 1
    assert gh.failed == []
    assert len(gh.prs_opened) == 1
    issue_num, branch, title, body = gh.prs_opened[0]
    assert branch.startswith("feat/issue-7-")
    assert title == "feat: add agent file"
    assert "Adds AGENT.txt with a marker" in body
    assert "Resolves #7" in body


def test_executor_failure_marks_failed(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    gh = FakeGh()
    executor = FakeExecutor(ok=False)
    orch = _make_orch(repo, tmp_path, gh, executor)

    issue = IssueRef(number=9, title="Executor dies", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is False
    assert gh.review == []
    assert gh.failed and gh.failed[0][0] == 9
    assert "boom" in gh.failed[0][1]
    assert gh.prs_opened == []


def test_no_commits_marks_failed(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    gh = FakeGh()
    executor = FakeExecutor(ok=True, commit=False)
    orch = _make_orch(repo, tmp_path, gh, executor)

    issue = IssueRef(number=11, title="docs: tweak", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is False
    assert gh.failed and "no commits" in gh.failed[0][1].lower()
    assert gh.prs_opened == []


def test_branch_type_falls_back_to_chore(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = repo_with_remote
    gh = FakeGh()
    executor = FakeExecutor(commit_subject="random subject", commit_body="")
    orch = _make_orch(repo, tmp_path, gh, executor)

    issue = IssueRef(number=12, title="some random thing", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is True
    assert gh.prs_opened[0][1].startswith("chore/issue-12-")
    assert gh.prs_opened[0][2] == "random subject"
