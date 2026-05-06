from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .executors.base import Executor, ExecResult
from .github_client import GitHubClient, IssueRef
from .issue_classifier import classify
from .logging_setup import get_logger
from .prompt_builder import build_initial
from .worktree_manager import Worktree, WorktreeManager

log = get_logger()


def _format_cost(result: ExecResult) -> str | None:
    """Render a one-line cost summary from the executor's per-run telemetry,
    or None if the executor did not report any. Goes into PR/issue comments,
    so it stays compact and free of paths or other host-specific noise.
    """
    parts: list[str] = []
    if result.cost_usd is not None:
        parts.append(f"~${result.cost_usd:.4f}")

    usage = result.usage or {}
    in_tok = usage.get("input_tokens")
    out_tok = usage.get("output_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    cache_create = usage.get("cache_creation_input_tokens")
    tok_bits: list[str] = []
    if isinstance(in_tok, int):
        tok_bits.append(f"in:{in_tok}")
    if isinstance(out_tok, int):
        tok_bits.append(f"out:{out_tok}")
    if isinstance(cache_read, int) and cache_read:
        tok_bits.append(f"cache_read:{cache_read}")
    if isinstance(cache_create, int) and cache_create:
        tok_bits.append(f"cache_creation:{cache_create}")
    if tok_bits:
        parts.append(" ".join(tok_bits))

    if isinstance(result.num_turns, int):
        parts.append(f"{result.num_turns} turns")

    if isinstance(result.duration_ms, int):
        secs = result.duration_ms / 1000
        if secs >= 60:
            m, s = divmod(int(secs), 60)
            parts.append(f"{m}m{s:02d}s")
        else:
            parts.append(f"{secs:.1f}s")

    if not parts:
        return None
    return " · ".join(parts)


def _redact_paths(text: str) -> str:
    """Strip local filesystem identifiers before sending text outside the host.

    Replaces the literal home path (/Users/<me> or /home/<me>) and the
    `$HOME` / `${HOME}` tokens with `~`, then collapses any remaining
    /Users/<x>/ or /home/<x>/ prefix to a `<redacted>` form so failure
    summaries — whether they end up in a public GitHub comment or in a
    centrally-collected log — do not leak the developer's username or
    directory layout.
    """
    home = str(Path.home())
    out = text.replace(home, "~")
    out = out.replace("${HOME}", "~").replace("$HOME", "~")
    out = re.sub(r"/Users/[^/\s'\"]+", "/Users/<redacted>", out)
    out = re.sub(r"/home/[^/\s'\"]+", "/home/<redacted>", out)
    return out


@dataclass
class TaskOutcome:
    issue_number: int
    success: bool
    pr_url: str | None
    summary: str


class Orchestrator:
    """Murloc only watches the board. It claims an issue, opens a worktree on a
    conventionally-named branch, hands the issue off to the executor, then —
    if the agent produced commits — pushes and opens a PR. It does not run
    tests or checks; that is the agent's responsibility.
    """

    def __init__(
        self,
        gh: GitHubClient,
        worktrees: WorktreeManager,
        executor: Executor,
        executor_timeout_sec: int,
        smoke_prompt: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.gh = gh
        self.worktrees = worktrees
        self.executor = executor
        self.executor_timeout_sec = executor_timeout_sec
        self.smoke_prompt = smoke_prompt
        self.dry_run = dry_run

    def process(self, issue: IssueRef) -> TaskOutcome:
        log.info("claim_attempt", issue=issue.number, title=issue.title)
        if not self.gh.claim(issue.number):
            log.info("skip_not_claimable", issue=issue.number)
            return TaskOutcome(issue.number, False, None, "Could not claim issue")
        log.info("claim_ok", issue=issue.number)

        type_ = classify(issue)
        log.info("classified", issue=issue.number, type=type_)

        wt: Worktree | None = None
        try:
            wt = self.worktrees.create(type_, issue.number, issue.title)
            log.info("worktree_created", issue=issue.number, path=str(wt.path), branch=wt.branch)

            log.info("prompt_build", issue=issue.number, smoke=self.smoke_prompt)
            prompt = build_initial(issue, smoke=self.smoke_prompt)
            log.info("prompt_built", issue=issue.number, chars=len(prompt))

            log.info("executor_run", issue=issue.number, branch=wt.branch)
            exec_result = self.executor.run(prompt, wt.path, self.executor_timeout_sec)
            log.info(
                "executor_done",
                issue=issue.number,
                ok=exec_result.ok,
                exit_code=exec_result.exit_code,
            )

            cost_line = _format_cost(exec_result)

            if not exec_result.ok:
                log.info("executor_failed", issue=issue.number, exit_code=exec_result.exit_code)
                tail = exec_result.stderr[-3000:] or exec_result.stdout[-3000:]
                summary = (
                    f"Agent exited with code {exec_result.exit_code}.\n\n"
                    f"```\n{_redact_paths(tail)}\n```"
                )
                if cost_line:
                    summary = f"{summary}\n\n**Cost:** {cost_line}"
                self.gh.mark_failed(issue.number, summary)
                return TaskOutcome(issue.number, False, None, summary)

            commits = self._commits_ahead(wt)
            log.info("commits_ahead", issue=issue.number, count=commits, branch=wt.branch)
            if commits == 0:
                log.info("no_commits", issue=issue.number)
                summary = "Agent exited cleanly but produced no commits — nothing to ship."
                if cost_line:
                    summary = f"{summary}\n\n**Cost:** {cost_line}"
                self.gh.mark_failed(issue.number, summary)
                return TaskOutcome(issue.number, False, None, summary)

            subject, body = self._first_commit_message(wt)
            pr_title = subject or f"{type_}: {issue.title}"
            pr_body = self._compose_pr_body(body, issue.number, commits)

            if self.dry_run:
                log.info(
                    "dry_run_skip",
                    issue=issue.number,
                    branch=wt.branch,
                    pr_title=pr_title,
                    commits=commits,
                )
                summary = (
                    f"[dry_run] {commits} commit(s) on `{wt.branch}`; "
                    f"would push and open PR titled \"{pr_title}\". "
                    f"Worktree left in place at {wt.path} for inspection."
                )
                return TaskOutcome(issue.number, True, None, summary)

            log.info("push_start", branch=wt.branch, remote=self.worktrees.push_remote)
            self._push(wt)
            log.info("push_done", branch=wt.branch)

            log.info("pr_open_start", issue=issue.number, branch=wt.branch, title=pr_title)
            pr_url = self.gh.open_pr(issue.number, wt.branch, pr_title, pr_body)
            log.info("pr_opened", issue=issue.number, url=pr_url)
            review_summary = f"PR opened with {commits} commit(s) on `{wt.branch}`."
            if cost_line:
                review_summary = f"{review_summary}\n\n**Cost:** {cost_line}"
            self.gh.mark_review(issue.number, pr_url, review_summary)
            log.info("issue_marked_review", issue=issue.number)

            self.worktrees.cleanup(issue.number)
            log.info("worktree_cleaned", issue=issue.number)
            return TaskOutcome(issue.number, True, pr_url, review_summary)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            log.error(
                "orchestrator_subprocess_error",
                issue=issue.number,
                cmd=e.cmd,
                exit_code=e.returncode,
                stderr=_redact_paths(stderr),
            )
            detail = stderr or (e.stdout or "").strip() or f"exit code {e.returncode}"
            public = _redact_paths(detail)
            self.gh.mark_failed(issue.number, f"Orchestrator error: {public}")
            return TaskOutcome(issue.number, False, None, f"Error: {public}")
        except Exception as e:
            log.exception("orchestrator_error", issue=issue.number)
            public = _redact_paths(repr(e))
            self.gh.mark_failed(issue.number, f"Orchestrator error: {public}")
            return TaskOutcome(issue.number, False, None, f"Error: {public}")

    @staticmethod
    def _compose_pr_body(agent_body: str, issue_number: int, commits: int) -> str:
        footer = (
            f"---\n"
            f"Resolves #{issue_number}\n"
            f"Mrglglgl! Generated by Murloc Manager · {commits} commit(s).\n"
        )
        if agent_body.strip():
            return f"{agent_body.rstrip()}\n\n{footer}"
        return footer

    def _first_commit_message(self, wt: Worktree) -> tuple[str, str]:
        """Return (subject, body) of the oldest commit on the branch ahead of base."""
        proc = subprocess.run(
            [
                "git", "log",
                f"{self.worktrees.base_branch}..HEAD",
                "--reverse",
                "--format=%B%x00",
            ],
            cwd=str(wt.path),
            check=True,
            capture_output=True,
            text=True,
        )
        chunks = [c for c in proc.stdout.split("\x00") if c.strip()]
        if not chunks:
            return "", ""
        first = chunks[0].strip("\n")
        if "\n" in first:
            subject, body = first.split("\n", 1)
            return subject.strip(), body.lstrip("\n")
        return first.strip(), ""

    def _commits_ahead(self, wt: Worktree) -> int:
        proc = subprocess.run(
            ["git", "rev-list", "--count", f"{self.worktrees.base_branch}..HEAD"],
            cwd=str(wt.path),
            check=True,
            capture_output=True,
            text=True,
        )
        return int(proc.stdout.strip() or "0")

    def _push(self, wt: Worktree) -> None:
        subprocess.run(
            ["git", "push", "-u", self.worktrees.push_remote, wt.branch],
            cwd=str(wt.path),
            check=True,
            capture_output=True,
            text=True,
        )
