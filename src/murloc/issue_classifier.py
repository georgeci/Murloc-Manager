from __future__ import annotations

import re

from .github_client import IssueRef

CONVENTIONAL_TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "chore",
    "refactor",
    "test",
    "docs",
    "style",
    "ci",
    "build",
    "perf",
)

_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?P<type>" + "|".join(CONVENTIONAL_TYPES) + r")(?:\([^)]*\))?\s*:",
    re.IGNORECASE,
)


def classify(issue: IssueRef, default: str = "chore") -> str:
    """Pick a conventional commit type for the branch from issue labels or title.

    Order:
    1. label `type:<x>` where <x> is a known conventional type
    2. label exactly matching a conventional type
    3. title prefix `feat:`, `fix(...): ` etc.
    4. fallback to `default`.
    """
    for raw in issue.labels:
        lbl = raw.strip().lower()
        if lbl.startswith("type:"):
            candidate = lbl.split(":", 1)[1].strip()
            if candidate in CONVENTIONAL_TYPES:
                return candidate
        if lbl in CONVENTIONAL_TYPES:
            return lbl

    m = _TITLE_PREFIX_RE.match(issue.title)
    if m:
        return m.group("type").lower()

    return default
