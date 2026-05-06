from __future__ import annotations

from .github_client import IssueRef

PROMPT_TEMPLATE = """\
You are an autonomous agent invoked by Murloc Manager to resolve a single GitHub Issue.

You are running inside a dedicated git worktree on a fresh branch. Your job:
1. Read the issue.
2. Make the changes needed to resolve it.
3. Run any tests, linters, or sanity checks YOU think are appropriate.
4. Commit your changes. **The subject and body of your FIRST commit will become
   the PR title and PR description**, so write them like a PR: clear subject,
   useful body explaining what changed and why. Subsequent commits are fine.
5. Stop.

Murloc Manager will push the branch, open the PR using your first commit
message, and label the issue for human review. Do NOT push or open a PR
yourself.

Issue #{number}: {title}
URL: {url}

Issue body:
---
{body}
---

Rules:
- Make the minimal diff that resolves the issue.
- Do not perform unrelated refactors, formatting-only changes, or dependency upgrades.
- Stay within this repository checkout.
- Do NOT dispatch subagents (no Task tool, no Explore agent). Read files
  directly with Read/Grep/Glob. The repo is small.
- If the issue is unclear or you cannot resolve it cleanly, exit non-zero with an
  explanation on stderr — Murloc will mark the issue blocked.
"""

SMOKE_PROMPT = """\
Smoke test. Do exactly the following and stop:

1. Read pyproject.toml in the current working directory.
2. Print one line of the form: "project=<name> python>=<version>"
   using the values you read.
3. Exit. Do not modify anything. Do not commit. Do not dispatch subagents
   (no Task tool, no Explore agent). Use the Read tool directly.
"""


def build_initial(issue: IssueRef, smoke: bool = False) -> str:
    if smoke:
        return SMOKE_PROMPT
    return PROMPT_TEMPLATE.format(
        number=issue.number,
        title=issue.title,
        url=issue.html_url,
        body=issue.body or "(no description)",
    )
