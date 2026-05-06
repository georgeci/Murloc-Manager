from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from github import Github
from github.Issue import Issue

from .project_state import LabelMap, State

_GQL_URL = "https://api.github.com/graphql"

_QUERY_PROJECT_META = """
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      id
      fields(first: 20) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
  }
}
"""

_QUERY_LIST_ITEMS = """
query($login: String!, $number: Int!, $after: String) {
  user(login: $login) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                optionId
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content {
            __typename
            ... on Issue {
              number title body url state
              labels(first: 20) { nodes { name } }
            }
          }
        }
      }
    }
  }
}
"""

_QUERY_ITEM_STATUS = """
query($itemId: ID!) {
  node(id: $itemId) {
    ... on ProjectV2Item {
      fieldValues(first: 20) {
        nodes {
          ... on ProjectV2ItemFieldSingleSelectValue {
            optionId
            field { ... on ProjectV2FieldCommon { name } }
          }
        }
      }
    }
  }
}
"""

_MUTATION_UPDATE_STATUS = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }
  ) {
    projectV2Item { id }
  }
}
"""


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


class ProjectsV2Client:
    """GitHubClient implementation that drives Murloc state via Projects v2 Status (GraphQL).

    Status option names expected in the project:
      "Todo"        → ready queue  (list_ready)
      "In Progress" → claimed      (claim)
      "In Review"   → review done  (mark_review)
      "Failed"      → failed       (mark_failed)
    """

    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        base_branch: str,
        project_owner: str,
        project_number: int,
        status_field: str = "Status",
        dry_run: bool = False,
    ) -> None:
        self._token = token
        self._gh = Github(token)
        self._repo = self._gh.get_repo(f"{owner}/{repo}")
        self._base_branch = base_branch
        self._project_owner = project_owner
        self._project_number = project_number
        self._status_field = status_field
        self._dry_run = dry_run

        self._project_id: str | None = None
        self._status_field_id: str | None = None
        self._status_options: dict[str, str] = {}  # option name → option id
        self._item_cache: dict[int, str] = {}       # issue number → project item id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _graphql(self, query: str, variables: dict) -> dict:
        payload = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(
            _GQL_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {body[:500]}") from exc
        if "errors" in result:
            raise RuntimeError(f"GitHub GraphQL errors: {result['errors']}")
        return result["data"]

    def _ensure_project_meta(self) -> None:
        if self._project_id is not None:
            return
        data = self._graphql(
            _QUERY_PROJECT_META,
            {"login": self._project_owner, "number": self._project_number},
        )
        project = data["user"]["projectV2"]
        self._project_id = project["id"]
        for field in project["fields"]["nodes"]:
            if not field.get("id"):
                continue
            if field.get("name") == self._status_field:
                self._status_field_id = field["id"]
                self._status_options = {opt["name"]: opt["id"] for opt in field["options"]}
                break
        if self._status_field_id is None:
            raise RuntimeError(
                f"Status field '{self._status_field}' not found in project "
                f"{self._project_owner}/projects/{self._project_number}"
            )

    def _set_status(self, item_id: str, status_name: str) -> None:
        option_id = self._status_options.get(status_name)
        if option_id is None:
            raise RuntimeError(f"Status option '{status_name}' not found in project field")
        self._graphql(
            _MUTATION_UPDATE_STATUS,
            {
                "projectId": self._project_id,
                "itemId": item_id,
                "fieldId": self._status_field_id,
                "optionId": option_id,
            },
        )

    def _current_status_option_id(self, item_id: str) -> str | None:
        data = self._graphql(_QUERY_ITEM_STATUS, {"itemId": item_id})
        for fv in data["node"]["fieldValues"]["nodes"]:
            if fv.get("field", {}).get("name") == self._status_field:
                return fv.get("optionId")
        return None

    # ------------------------------------------------------------------
    # GitHubClient protocol
    # ------------------------------------------------------------------

    def list_ready(self) -> list[IssueRef]:
        self._ensure_project_meta()
        todo_id = self._status_options.get("Todo")
        if todo_id is None:
            raise RuntimeError("'Todo' option not found in project Status field")

        results: list[IssueRef] = []
        cursor: str | None = None
        while True:
            data = self._graphql(
                _QUERY_LIST_ITEMS,
                {
                    "login": self._project_owner,
                    "number": self._project_number,
                    "after": cursor,
                },
            )
            page = data["user"]["projectV2"]["items"]
            for node in page["nodes"]:
                content = node.get("content") or {}
                if content.get("__typename") != "Issue":
                    continue
                if content.get("state") != "OPEN":
                    continue
                status_option_id: str | None = None
                for fv in node["fieldValues"]["nodes"]:
                    if fv.get("field", {}).get("name") == self._status_field:
                        status_option_id = fv.get("optionId")
                        break
                if status_option_id != todo_id:
                    continue
                issue_number: int = content["number"]
                self._item_cache[issue_number] = node["id"]
                results.append(
                    IssueRef(
                        number=issue_number,
                        title=content["title"],
                        body=content.get("body") or "",
                        labels=[lbl["name"] for lbl in content["labels"]["nodes"]],
                        html_url=content["url"],
                    )
                )
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        return results

    def claim(self, issue_number: int) -> bool:
        self._ensure_project_meta()
        item_id = self._item_cache.get(issue_number)
        if item_id is None:
            return False
        current = self._current_status_option_id(item_id)
        if current != self._status_options.get("Todo"):
            return False
        if self._dry_run:
            return True
        self._set_status(item_id, "In Progress")
        return True

    def mark_review(self, issue_number: int, pr_url: str, summary: str) -> None:
        if self._dry_run:
            return
        item_id = self._item_cache.get(issue_number)
        if item_id:
            self._set_status(item_id, "In Review")
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(f"Mrglglgl! PR ready for review: {pr_url}\n\n{summary}")

    def mark_failed(self, issue_number: int, summary: str) -> None:
        if self._dry_run:
            return
        item_id = self._item_cache.get(issue_number)
        if item_id:
            self._set_status(item_id, "Failed")
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(f"Mrglgl... agent failed.\n\n{summary}")

    def open_pr(self, issue_number: int, branch: str, title: str, body: str) -> str:
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=self._base_branch,
        )
        return pr.html_url
