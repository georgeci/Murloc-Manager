# Murloc Manager

> mrglglgl — local orchestrator that drives Claude Code CLI through GitHub Issues.

A tiny chaotic Murloc runs around your GitHub Issues, claims one labeled
`agent:ready`, spawns a git worktree, hands the issue to Claude Code CLI,
runs your checks, opens a PR, and labels it `agent:review` for you to merge.

## Pipeline

```
GitHub Issue (agent:ready)
  ↓ claim → agent:running
worktree per task (murloc/issue-<n>-<slug>)
  ↓
Claude Code CLI (subprocess) edits files
  ↓
checks (ruff + pytest by default; configurable to Gradle etc.)
  ↓ retry up to N times on failure
push branch → open PR
  ↓
Issue → agent:review (you merge)
```

## v1 scope

In v1: worktree-per-task, Claude CLI executor, retry policy, single-task
processing. NOT in v1: scope detector, diff guard, LM Studio router, Codex,
parallel tasks. Those are tracked as separate Issues.

## Quickstart

Requires Python 3.12+, git, and the `claude` CLI installed and authenticated.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.toml config.toml          # edit owner/repo
cp .env.example .env                         # set GITHUB_TOKEN

# One-shot: pick first agent:ready issue and run it.
murloc run-once

# Long-running: poll every 60s.
murloc poll --interval 60

# Status: print configured repo + active worktrees.
murloc status
```

### GitHub setup (one-time)

1. Create labels: `agent:ready`, `agent:running`, `agent:review`,
   `agent:failed`, `agent:blocked`, `agent:manual`.
2. Branch protection on `main`: require PR review (only you merge).
3. `GITHUB_TOKEN` with `repo` scope in `.env`.

## Configuration

`config.toml` controls everything. The check commands are an array, so to
target an Android/KMP repo later you swap them for Gradle without code
changes:

```toml
[checks]
commands = [
    ["./gradlew", ":shared:compileKotlinJvm", "-q"],
    ["./gradlew", ":composeApp:compileDebugKotlinAndroid", "-q"],
]
```

## Development

```bash
ruff check .
pytest -q
```

## Layout

```
src/murloc/
  cli.py              # click entry point
  config.py           # pydantic settings from config.toml + .env
  logging_setup.py    # structlog
  github_client.py    # PyGithub wrapper, claim/PR/labels
  project_state.py    # FSM over labels
  worktree_manager.py # git worktree per issue
  executors/
    base.py           # Executor protocol
    claude_cli.py     # subprocess `claude --print ...`
  prompt_builder.py   # initial + retry prompts
  checks_runner.py    # run configured check commands
  retry_policy.py     # max attempts gate
  orchestrator.py     # the pipeline
```

## Principle

> LLM proposes. Murloc Manager decides. Git/checks verify. Human merges.
