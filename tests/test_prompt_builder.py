from __future__ import annotations

from murloc.github_client import IssueRef
from murloc.prompt_builder import build_initial


def _issue(
    number: int = 42,
    title: str = "Add a feature",
    body: str = "Please add X.",
    html_url: str = "https://github.com/org/repo/issues/42",
) -> IssueRef:
    return IssueRef(number=number, title=title, body=body, labels=[], html_url=html_url)


def test_build_initial_includes_issue_number() -> None:
    prompt = build_initial(_issue(number=99))
    assert "Issue #99" in prompt


def test_build_initial_includes_title() -> None:
    prompt = build_initial(_issue(title="Fix the murloc dance"))
    assert "Fix the murloc dance" in prompt


def test_build_initial_includes_url() -> None:
    prompt = build_initial(_issue(html_url="https://github.com/org/repo/issues/5"))
    assert "https://github.com/org/repo/issues/5" in prompt


def test_build_initial_includes_body() -> None:
    prompt = build_initial(_issue(body="Do the thing."))
    assert "Do the thing." in prompt


def test_build_initial_empty_body_shows_placeholder() -> None:
    issue = IssueRef(number=1, title="t", body="", labels=[], html_url="x")
    prompt = build_initial(issue)
    assert "(no description)" in prompt


def test_build_initial_none_body_shows_placeholder() -> None:
    issue = IssueRef(number=1, title="t", body=None, labels=[], html_url="x")  # type: ignore[arg-type]
    prompt = build_initial(issue)
    assert "(no description)" in prompt


def test_build_initial_smoke_returns_smoke_prompt() -> None:
    prompt = build_initial(_issue(), smoke=True)
    assert "Smoke test" in prompt
    assert "pyproject.toml" in prompt


def test_build_initial_smoke_does_not_contain_issue_number() -> None:
    prompt = build_initial(_issue(number=77), smoke=True)
    assert "Issue #77" not in prompt


def test_build_initial_no_smoke_by_default() -> None:
    prompt = build_initial(_issue())
    assert "Smoke test" not in prompt
    assert "Issue #" in prompt
