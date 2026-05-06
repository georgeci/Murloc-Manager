from __future__ import annotations

import time
from pathlib import Path

import click

from .config import Settings, load_settings
from .executors.claude_cli import ClaudeCliExecutor
from .github_client import PyGithubClient
from .logging_setup import get_logger, setup_logging
from .orchestrator import Orchestrator
from .project_state import LabelMap
from .worktree_manager import WorktreeManager

log = get_logger()


def _build_orchestrator(settings: Settings) -> tuple[Orchestrator, PyGithubClient]:
    if not settings.github_token:
        raise click.ClickException("GITHUB_TOKEN is missing in environment / .env")

    labels = LabelMap(
        ready=settings.labels.ready,
        running=settings.labels.running,
        review=settings.labels.review,
        failed=settings.labels.failed,
        blocked=settings.labels.blocked,
    )
    gh = PyGithubClient(
        token=settings.github_token,
        owner=settings.github.owner,
        repo=settings.github.repo,
        base_branch=settings.github.base_branch,
        labels=labels,
        dry_run=settings.runtime.dry_run,
    )
    wm = WorktreeManager(
        repo_root=Path(settings.paths.repo_root).resolve(),
        worktrees_root=Path(settings.paths.worktrees_root).resolve(),
        base_branch=settings.github.base_branch,
    )
    executor = ClaudeCliExecutor(
        command=settings.executor.command,
        extra_args=settings.executor.extra_args,
    )
    orch = Orchestrator(
        gh=gh,
        worktrees=wm,
        executor=executor,
        executor_timeout_sec=settings.executor.timeout_sec,
        smoke_prompt=settings.runtime.smoke_prompt,
        dry_run=settings.runtime.dry_run,
    )
    return orch, gh


@click.group()
@click.option("--config", "config_path", default="config.toml", show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
@click.pass_context
def main(ctx: click.Context, config_path: str, log_level: str) -> None:
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings(config_path)


@main.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    settings: Settings = ctx.obj["settings"]
    wt_root = Path(settings.paths.worktrees_root)
    click.echo(f"repo: {settings.github.owner}/{settings.github.repo}")
    click.echo(f"base_branch: {settings.github.base_branch}")
    click.echo(f"worktrees_root: {wt_root}")
    if wt_root.exists():
        for p in wt_root.iterdir():
            if p.is_dir():
                click.echo(f"  - {p.name}")
    else:
        click.echo("  (no worktrees)")


@main.command("run-once")
@click.pass_context
def run_once_cmd(ctx: click.Context) -> None:
    settings: Settings = ctx.obj["settings"]
    orch, gh = _build_orchestrator(settings)
    issues = gh.list_ready()
    if not issues:
        click.echo("No agent:ready issues. Mrglgl?")
        return
    issue = issues[0]
    click.echo(f"Picking issue #{issue.number}: {issue.title}")
    log.info("run_once_pick", issue=issue.number, title=issue.title)
    outcome = orch.process(issue)
    click.echo(f"Done. success={outcome.success} pr={outcome.pr_url}")
    click.echo(outcome.summary)


@main.command("poll")
@click.option("--interval", default=60, show_default=True, type=int)
@click.pass_context
def poll_cmd(ctx: click.Context, interval: int) -> None:
    settings: Settings = ctx.obj["settings"]
    orch, gh = _build_orchestrator(settings)
    click.echo(f"Polling every {interval}s. Ctrl+C to stop.")
    while True:
        try:
            issues = gh.list_ready()
            if issues:
                issue = issues[0]
                click.echo(f"Picking issue #{issue.number}: {issue.title}")
                outcome = orch.process(issue)
                click.echo(f"Done. success={outcome.success} pr={outcome.pr_url}")
            else:
                log.debug("no_ready_issues")
        except Exception:
            log.exception("poll_iteration_error")
        time.sleep(interval)


if __name__ == "__main__":
    main()
