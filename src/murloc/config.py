from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class ProjectCfg(BaseModel):
    owner_type: str = "user"
    owner: str | None = None  # defaults to github.owner when unset
    number: int
    status_field: str = "Status"

    @field_validator("owner_type")
    @classmethod
    def _only_user_owner(cls, v: str) -> str:
        if v != "user":
            raise ValueError(
                f"github.project.owner_type='{v}' is not supported; "
                "only 'user' is implemented."
            )
        return v


class GithubCfg(BaseModel):
    owner: str | None = None
    repo: str | None = None
    base_branch: str = "main"
    project: ProjectCfg | None = None


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


class RuntimeCfg(BaseModel):
    dry_run: bool = False
    smoke_prompt: bool = False


class Settings(BaseModel):
    github: GithubCfg
    labels: LabelsCfg = Field(default_factory=LabelsCfg)
    executor: ExecutorCfg = Field(default_factory=ExecutorCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)
    runtime: RuntimeCfg = Field(default_factory=RuntimeCfg)

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

    # Env vars override config file, but both are "explicit" and beat auto-detect.
    if not settings.github.owner:
        env_owner = os.getenv("GITHUB_OWNER", "").strip()
        if env_owner:
            settings.github.owner = env_owner
    if not settings.github.repo:
        env_repo = os.getenv("GITHUB_REPO", "").strip()
        if env_repo:
            settings.github.repo = env_repo

    # Auto-detect from git remote when either value is still missing.
    if not settings.github.owner or not settings.github.repo:
        detected_owner, detected_repo = _detect_github_owner_repo(settings.paths.repo_root)
        if not settings.github.owner:
            settings.github.owner = detected_owner
        if not settings.github.repo:
            settings.github.repo = detected_repo

    return settings


_GITHUB_URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"
)


def _parse_github_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) from a GitHub remote URL, or None if not a GitHub URL."""
    m = _GITHUB_URL_RE.match(url)
    if not m:
        return None
    return m.group("owner"), m.group("repo")


def _detect_github_owner_repo(repo_root: str) -> tuple[str, str]:
    """Auto-detect GitHub owner and repo from the 'origin' remote of a local repo."""
    root = Path(repo_root).resolve()
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "git executable not found; set github.owner/repo explicitly"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"timed out running 'git remote get-url origin' in {root}; "
            "set github.owner/repo explicitly"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"failed to run git in {root}: {exc}; set github.owner/repo explicitly"
        ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stderr_lower = stderr.lower()
        if "not a git repository" in stderr_lower:
            raise ValueError(
                f"not a git repository at {root}; set github.owner/repo explicitly"
            )
        if "no such remote" in stderr_lower or "no such remote 'origin'" in stderr_lower:
            raise ValueError(
                "git remote 'origin' is not configured; set github.owner/repo explicitly"
            )
        raise ValueError(
            f"git remote get-url origin failed: {stderr or '(no stderr)'}; "
            "set github.owner/repo explicitly"
        )

    url = proc.stdout.strip()
    result = _parse_github_url(url)
    if result is None:
        raise ValueError(
            f"remote 'origin' is not a GitHub URL: {url}; set github.owner/repo explicitly"
        )
    return result


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
