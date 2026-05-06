from __future__ import annotations

from murloc.github_client import IssueRef
from murloc.issue_classifier import classify


def _issue(title: str = "x", labels: list[str] | None = None) -> IssueRef:
    return IssueRef(number=1, title=title, body="", labels=labels or [], html_url="x")


def test_classify_from_type_label() -> None:
    assert classify(_issue(labels=["type:feat"])) == "feat"


def test_classify_from_bare_label() -> None:
    assert classify(_issue(labels=["bug", "fix"])) == "fix"


def test_classify_from_title_prefix() -> None:
    assert classify(_issue(title="feat: add murloc dance")) == "feat"
    assert classify(_issue(title="FIX(parser): handle empty body")) == "fix"


def test_classify_default_chore() -> None:
    assert classify(_issue(title="random thing", labels=["good first issue"])) == "chore"


def test_classify_label_overrides_title() -> None:
    assert classify(_issue(title="feat: x", labels=["type:fix"])) == "fix"


def test_classify_unknown_type_label_falls_through_to_title() -> None:
    assert classify(_issue(title="docs: readme", labels=["type:nonsense"])) == "docs"


def test_classify_all_known_type_labels() -> None:
    known = ("feat", "fix", "chore", "refactor", "test", "docs", "style", "ci", "build", "perf")
    for t in known:
        assert classify(_issue(labels=[f"type:{t}"])) == t


def test_classify_bare_label_case_insensitive() -> None:
    assert classify(_issue(labels=["FIX"])) == "fix"
    assert classify(_issue(labels=["FEAT"])) == "feat"


def test_classify_title_with_scope() -> None:
    assert classify(_issue(title="refactor(auth): clean up tokens")) == "refactor"


def test_classify_label_over_unknown_type_label() -> None:
    assert classify(_issue(title="x", labels=["type:unknown", "fix"])) == "fix"


def test_classify_empty_labels_and_title() -> None:
    assert classify(_issue(title="", labels=[])) == "chore"
