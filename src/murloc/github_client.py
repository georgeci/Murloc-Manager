from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from github import Github
from github.Issue import Issue

from .project_state import LabelMap, State


@dataclass
class IssueRef:
    number: int
    title: str
    body: str
    labels: list[str]
    html_url: str


class GitHubClient(Protocol):
    def list_ready(self) -> list[IssueRef]: ...
    def claim(self, issue_number: int) -> bool: ...
    def mark_review(self, issue_number: int, pr_url: str, summary: str) -> None: ...
    def mark_failed(self, issue_number: int, summary: str) -> None: ...
    def open_pr(self, issue_number: int, branch: str, title: str, body: str) -> str: ...


class PyGithubClient:
    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        base_branch: str,
        labels: LabelMap,
        dry_run: bool = False,
    ) -> None:
        self._gh = Github(token)
        self._repo = self._gh.get_repo(f"{owner}/{repo}")
        self._base_branch = base_branch
        self._labels = labels
        self._dry_run = dry_run

    def _to_ref(self, issue: Issue) -> IssueRef:
        return IssueRef(
            number=issue.number,
            title=issue.title,
            body=issue.body or "",
            labels=[lbl.name for lbl in issue.labels],
            html_url=issue.html_url,
        )

    def list_ready(self) -> list[IssueRef]:
        issues = self._repo.get_issues(state="open", labels=[self._labels.ready])
        return [self._to_ref(i) for i in issues if i.pull_request is None]

    def claim(self, issue_number: int) -> bool:
        issue = self._repo.get_issue(issue_number)
        names = {lbl.name for lbl in issue.labels}
        if self._labels.running in names:
            return False
        if self._labels.ready not in names:
            return False
        if self._dry_run:
            return True
        new_labels = (names - {self._labels.ready}) | {self._labels.running}
        issue.set_labels(*new_labels)
        return True

    def _swap_label(self, issue_number: int, new_label: str) -> None:
        if self._dry_run:
            return
        issue = self._repo.get_issue(issue_number)
        names = {lbl.name for lbl in issue.labels} - self._labels.all_agent_labels()
        names.add(new_label)
        issue.set_labels(*names)

    def mark_review(self, issue_number: int, pr_url: str, summary: str) -> None:
        if self._dry_run:
            return
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(f"Mrglglgl! PR ready for review: {pr_url}\n\n{summary}")
        self._swap_label(issue_number, self._labels.review)

    def mark_failed(self, issue_number: int, summary: str) -> None:
        if self._dry_run:
            return
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(f"Mrglgl... agent failed.\n\n{summary}")
        self._swap_label(issue_number, self._labels.failed)

    def open_pr(self, issue_number: int, branch: str, title: str, body: str) -> str:
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=self._base_branch,
        )
        return pr.html_url

    def state_of(self, issue_number: int) -> State:
        issue = self._repo.get_issue(issue_number)
        return self._labels.state_of([lbl.name for lbl in issue.labels])
