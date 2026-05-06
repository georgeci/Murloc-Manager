from __future__ import annotations

from murloc.github_client import IssueRef
from murloc.prompt_builder import SMOKE_PROMPT, build_initial


def _issue(number: int = 5, title: str = "fix: broken thing", body: str = "please fix") -> IssueRef:
    return IssueRef(number=number, title=title, body=body, labels=[], html_url="http://x/issues/5")


def test_smoke_returns_smoke_prompt() -> None:
    assert build_initial(_issue(), smoke=True) == SMOKE_PROMPT


def test_non_smoke_includes_issue_number() -> None:
    assert "Issue #5" in build_initial(_issue())


def test_non_smoke_includes_title() -> None:
    issue = _issue()
    assert issue.title in build_initial(issue)


def test_non_smoke_includes_body() -> None:
    issue = _issue()
    assert issue.body in build_initial(issue)


def test_non_smoke_includes_url() -> None:
    issue = _issue()
    assert issue.html_url in build_initial(issue)


def test_empty_body_uses_placeholder() -> None:
    issue = IssueRef(number=1, title="t", body="", labels=[], html_url="x")
    assert "(no description)" in build_initial(issue)


def test_smoke_default_is_false() -> None:
    assert build_initial(_issue()) != SMOKE_PROMPT
