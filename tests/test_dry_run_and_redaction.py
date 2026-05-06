from __future__ import annotations

from pathlib import Path

import pytest

from murloc.github_client import IssueRef
from murloc.orchestrator import Orchestrator, _redact_paths
from murloc.worktree_manager import WorktreeManager

from .test_orchestrator_smoke import FakeExecutor, FakeGh, repo_with_remote  # noqa: F401


class TestRedactPaths:
    def test_replaces_home_directory(self) -> None:
        home = str(Path.home())
        text = f"failed reading {home}/secret/file"
        assert _redact_paths(text) == "failed reading ~/secret/file"

    def test_replaces_users_prefix(self) -> None:
        text = "fatal: '/Users/alice/Developer/foo' is not a working tree"
        assert "/Users/alice" not in _redact_paths(text)
        assert "/Users/<redacted>" in _redact_paths(text)

    def test_replaces_home_prefix(self) -> None:
        text = "stat /home/bob/foo: no such file"
        assert "/home/bob" not in _redact_paths(text)
        assert "/home/<redacted>" in _redact_paths(text)

    def test_replaces_dollar_home_token(self) -> None:
        text = "cwd was $HOME and ${HOME}/x"
        out = _redact_paths(text)
        assert "$HOME" not in out
        assert "${HOME}" not in out
        assert out.count("~") >= 2


def test_dry_run_skips_push_and_pr_open(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, remote = repo_with_remote
    gh = FakeGh()
    executor = FakeExecutor(commit_subject="feat: dry run lands no PR", commit_body="")
    wm = WorktreeManager(repo_root=repo, worktrees_root=tmp_path / "wt", base_branch="main")
    orch = Orchestrator(
        gh=gh, worktrees=wm, executor=executor, executor_timeout_sec=60, dry_run=True
    )

    issue = IssueRef(number=42, title="dry one", body="", labels=[], html_url="x")
    outcome = orch.process(issue)

    assert outcome.success is True
    assert outcome.pr_url is None
    assert "[dry_run]" in outcome.summary
    # The agent committed but Murloc did not push or open a PR.
    assert gh.prs_opened == []
    assert gh.review == []
    assert gh.failed == []
    # Branch never reached the remote.
    import subprocess
    proc = subprocess.run(
        ["git", "branch", "-r"], cwd=str(remote), capture_output=True, text=True
    )
    assert "chore/issue-42" not in proc.stdout
    assert "feat/issue-42" not in proc.stdout


@pytest.mark.parametrize("running_label,ready_label,expected", [
    ({"agent:running"}, set(), False),
    (set(), set(), False),
    (set(), {"agent:ready"}, True),
])
def test_pygithub_claim_dry_run_respects_labels(
    running_label: set[str], ready_label: set[str], expected: bool, mocker: object
) -> None:
    """Under dry_run, claim() must still read labels and return False when the
    issue is already running or not yet ready — only the label-write side
    effect is suppressed."""
    from murloc.github_client import PyGithubClient
    from murloc.project_state import LabelMap

    fake_labels = [type("L", (), {"name": n}) for n in running_label | ready_label]
    fake_issue = type("I", (), {"labels": fake_labels, "set_labels": lambda *a, **k: None})()
    fake_repo = type("R", (), {"get_issue": lambda self, n: fake_issue})()

    client = PyGithubClient.__new__(PyGithubClient)
    client._repo = fake_repo  # type: ignore[attr-defined]
    client._base_branch = "main"  # type: ignore[attr-defined]
    client._labels = LabelMap(  # type: ignore[attr-defined]
        ready="agent:ready",
        running="agent:running",
        review="agent:review",
        failed="agent:failed",
        blocked="agent:blocked",
    )
    client._dry_run = True  # type: ignore[attr-defined]

    assert client.claim(1) is expected
