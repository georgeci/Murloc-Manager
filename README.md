# Murloc Manager

> mrglglgl — local orchestrator that drives Claude Code CLI through GitHub Issues.

A tiny chaotic Murloc watches your GitHub Issues, claims one labeled
`agent:ready`, opens a worktree on a conventionally-named branch, hands the
issue to Claude Code CLI, then ships whatever the agent committed and labels
the issue `agent:review` for you to merge.

Murloc itself does **not** run tests, linters, or retries. The agent decides
how to verify its own work. Murloc is a dispatcher and a finisher, not a
referee.

## Pipeline

```
GitHub Issue (agent:ready)
  ↓ claim → agent:running
classify type from label `type:<x>` / title prefix → feat|fix|chore|...
  ↓
worktree on branch <type>/issue-<n>-<slug>
  ↓
Claude Code CLI edits + commits (it picks its own checks)
  ↓
push branch
  ↓ first commit subject/body becomes the PR title/description
open PR (Resolves #N footer appended)
  ↓
Issue → agent:review (you merge)
```

If the agent exits non-zero, or exits cleanly without committing anything,
Murloc moves the issue to `agent:failed` and leaves the worktree for you to
inspect.

## v1 scope

In v1: poll → claim → worktree+branch → executor → push → PR → review.
NOT in v1: scope detector, diff guard, LM Studio router, Codex executor,
parallel tasks. Those are tracked as separate Issues.

## Quickstart

Requires Python 3.12+, git, the `gh` CLI (recommended — used as auth
fallback), and the `claude` CLI installed and authenticated.

### Pointing at a project

Edit `config.toml`:

- `[github] owner` + `[github] repo` — which GitHub repo to watch for
  `agent:ready` issues.
- `[paths] repo_root` — absolute path to the **local clone** of that
  repo. Worktrees and pushes happen from here. Defaults to `.` (CWD).

You can run Murloc from anywhere as long as `repo_root` points at a
real git checkout of the configured GitHub repo.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.toml config.toml          # set [github] owner/repo + [paths] repo_root
cp .env.example .env                         # GITHUB_TOKEN optional — falls back to `gh auth token`

# One-shot: pick first agent:ready issue and run it.
murloc run-once

# Long-running: poll every 60s.
murloc poll --interval 60

# Status: print configured repo + active worktrees.
murloc status
```

### GitHub setup (one-time)

1. Create labels: `agent:ready`, `agent:running`, `agent:review`,
   `agent:failed`, `agent:blocked`. Optionally `type:feat`, `type:fix`,
   `type:chore`, etc. for branch classification.
2. Branch protection on `main`: require PR review (only you merge).
3. Auth: either `GITHUB_TOKEN` with `repo` scope in `.env`, **or** have
   the `gh` CLI authenticated (`gh auth login`) — Murloc falls back to
   `gh auth token` automatically.

### Optional: drive Murloc from a Projects v2 board

When `[github.project]` is configured in `config.toml`, Murloc reads the
ready queue and flips statuses directly via GraphQL — no GitHub Actions
workflow needed.

Your project board's Status field must have these option names:

| Status option | Murloc state |
|---|---|
| `Todo` | ready to pick up |
| `In Progress` | claimed by agent |
| `In Review` | PR opened, awaiting human merge |
| `Failed` | agent failed or produced no commits |

Setup:

1. Create a fine-grained PAT with **Projects: Read and write** (user
   permission) and **Issues: Read & write** (repository permission). Set
   it as `GITHUB_TOKEN` in `.env`.
2. Add a `[github.project]` block to `config.toml` (see `config.example.toml`):

```toml
[github.project]
owner_type   = "user"
number       = 3          # /users/<you>/projects/3
status_field = "Status"   # name of the single-select field on the board
```

When `[github.project]` is present, labels (`agent:ready`, etc.) are no
longer used for workflow state — they remain available for classification
(e.g. `type:fix`, `type:chore`).

## Branch naming

Murloc picks a conventional commit type using this order:

1. Issue label `type:<x>` where `<x>` ∈ feat|fix|chore|refactor|test|docs|style|ci|build|perf
2. Bare conventional label (e.g. just `fix`)
3. Title prefix `feat:`, `fix(scope):`, etc.
4. Fallback: `chore`

Branch is `<type>/issue-<n>-<slugified-title>`.

## Agent contract

The prompt tells the agent:

- Edit files inside the worktree.
- Run whatever checks you think appropriate.
- Commit. **Your first commit's subject becomes the PR title; its body
  becomes the PR description.** Murloc appends a `Resolves #N` footer.
- Do not push or open a PR yourself.
- Exit non-zero (with stderr) if you cannot finish — Murloc will mark the
  issue failed.

## Development

```bash
ruff check .
pytest -q
```

### Debugging options

Two `[runtime]` flags in `config.toml` help with local iteration:

- `dry_run = true` — Murloc skips all writes to GitHub (no label swaps, no
  comments, no PRs). The worktree and commits are left in place for inspection.
- `smoke_prompt = true` — sends a trivial "read pyproject.toml and print one
  line" prompt instead of the real issue prompt. Verifies the executor pipeline
  end-to-end without asking the agent to do real work.

## Layout

```
src/murloc/
  cli.py               # click entry point
  config.py            # pydantic settings from config.toml + .env
  logging_setup.py     # structlog
  github_client.py     # PyGithubClient (labels) + ProjectsV2Client (GraphQL)
  project_state.py     # label-FSM helpers
  worktree_manager.py  # git worktree per issue
  issue_classifier.py  # pick conventional commit type
  executors/
    base.py            # Executor protocol
    claude_cli.py      # subprocess `claude --print ...`
  prompt_builder.py    # builds the agent's task prompt
  orchestrator.py      # the dispatcher pipeline
```

## Principle

> Murloc dispatches. The agent verifies and writes the PR description.
> Git carries the work. Human merges.
