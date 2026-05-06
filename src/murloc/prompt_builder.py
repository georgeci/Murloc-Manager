from __future__ import annotations

from .github_client import IssueRef

PROMPT_TEMPLATE = """\
You are an autonomous agent invoked by Murloc Manager to resolve a single GitHub Issue.

Issue #{number}: {title}
URL: {url}

Issue body:
---
{body}
---

Rules:
- Make the minimal diff that resolves the issue.
- Do not perform unrelated refactors, formatting-only changes, or dependency upgrades.
- Stay within this repository checkout — do not modify files outside it.
- After editing, the harness will run these checks:
{checks}
- If checks fail, you will be invoked again with the failure output and asked to fix.

When done editing, simply stop. Do not commit, push, or open a PR — Murloc Manager will do that.
"""

RETRY_SUFFIX = """\

Previous attempt #{attempt} failed. Last check command: {command}
Last stderr (truncated):
---
{stderr}
---
Last stdout (truncated):
---
{stdout}
---
Fix the failing check. Keep changes minimal.
"""


def _fmt_checks(commands: list[list[str]]) -> str:
    return "\n".join(f"  - {' '.join(c)}" for c in commands)


def build_initial(issue: IssueRef, check_commands: list[list[str]]) -> str:
    return PROMPT_TEMPLATE.format(
        number=issue.number,
        title=issue.title,
        url=issue.html_url,
        body=issue.body or "(no description)",
        checks=_fmt_checks(check_commands),
    )


def build_retry(base_prompt: str, attempt: int, command: str, stdout: str, stderr: str) -> str:
    truncate = 4000
    return base_prompt + RETRY_SUFFIX.format(
        attempt=attempt,
        command=command,
        stderr=stderr[-truncate:],
        stdout=stdout[-truncate:],
    )
