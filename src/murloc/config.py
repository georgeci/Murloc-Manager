from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


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
    timeout_sec: int = 600


class RetryCfg(BaseModel):
    max_attempts: int = 3


class ChecksCfg(BaseModel):
    commands: list[list[str]]

    @field_validator("commands")
    @classmethod
    def _non_empty(cls, v: list[list[str]]) -> list[list[str]]:
        if not v:
            raise ValueError(
                "checks.commands must contain at least one command "
                "(e.g. [['ruff', 'check', '.']])"
            )
        for cmd in v:
            if not cmd:
                raise ValueError("checks.commands entries must be non-empty argv lists")
        return v


class PathsCfg(BaseModel):
    worktrees_root: str = ".murloc/worktrees"
    repo_root: str = "."


class Settings(BaseModel):
    github: GithubCfg
    labels: LabelsCfg = Field(default_factory=LabelsCfg)
    executor: ExecutorCfg = Field(default_factory=ExecutorCfg)
    retry: RetryCfg = Field(default_factory=RetryCfg)
    checks: ChecksCfg
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
    settings.github_token = os.getenv("GITHUB_TOKEN", "")
    return settings
