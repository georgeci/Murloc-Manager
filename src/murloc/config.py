from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class GithubCfg(BaseModel):
    owner: str
    repo: str
    base_branch: str = "main"


class LabelsCfg(BaseModel):
    ready: str = "agent:ready"
    running: str = "agent:running"
    review: str = "agent:review"
    failed: str = "agent:failed"
    blocked: str = "agent:blocked"


class ExecutorCfg(BaseModel):
    kind: str = "claude_cli"
    command: str = "claude"
    extra_args: list[str] = Field(default_factory=list)
    timeout_sec: int = 1800


class PathsCfg(BaseModel):
    worktrees_root: str = ".murloc/worktrees"
    repo_root: str = "."


class Settings(BaseModel):
    github: GithubCfg
    labels: LabelsCfg = Field(default_factory=LabelsCfg)
    executor: ExecutorCfg = Field(default_factory=ExecutorCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)

    github_token: str = ""


def load_settings(config_path: str | Path = "config.toml") -> Settings:
    load_dotenv()
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.toml to config.toml and fill it in."
        )
    with path.open("rb") as f:
        data = tomllib.load(f)
    settings = Settings.model_validate(data)
    settings.github_token = _resolve_token() or _gh_auth_token()
    return settings


_VALID_TOKEN_PREFIXES = ("ghp_", "gho_", "ghs_", "ghu_", "ghr_", "github_pat_")


def _resolve_token() -> str:
    raw = os.getenv("GITHUB_TOKEN", "").strip()
    if not raw:
        return ""
    if not raw.startswith(_VALID_TOKEN_PREFIXES):
        return ""
    if "your_token" in raw or "your-token" in raw:
        return ""
    return raw


def _gh_auth_token() -> str:
    """Fallback: ask the gh CLI for its current token."""
    if shutil.which("gh") is None:
        return ""
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()
