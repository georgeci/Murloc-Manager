from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from murloc.config import _resolve_token, load_settings


def test_resolve_token_valid_ghp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc123")
    assert _resolve_token() == "ghp_abc123"


def test_resolve_token_valid_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_abc123")
    assert _resolve_token() == "github_pat_abc123"


def test_resolve_token_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    assert _resolve_token() == ""


def test_resolve_token_invalid_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "notavalidtoken")
    assert _resolve_token() == ""


def test_resolve_token_placeholder_your_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_your_token_here")
    assert _resolve_token() == ""


def test_resolve_token_placeholder_your_dash_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_your-token")
    assert _resolve_token() == ""


def test_resolve_token_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "  ghp_abc  ")
    assert _resolve_token() == "ghp_abc"


def test_load_settings_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "no_such.toml")


def test_load_settings_minimal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[github]\nowner = "acme"\nrepo = "widgets"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings = load_settings(cfg)
    assert settings.github.owner == "acme"
    assert settings.github.repo == "widgets"
    assert settings.github.base_branch == "main"
    assert settings.labels.ready == "agent:ready"
    assert settings.executor.kind == "claude_cli"
    assert settings.runtime.dry_run is False


def test_load_settings_token_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[github]\nowner = "a"\nrepo = "b"\n')
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_mytoken")
    settings = load_settings(cfg)
    assert settings.github_token == "ghp_mytoken"


def test_load_settings_custom_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[github]\nowner = "a"\nrepo = "b"\n'
        '[labels]\nready = "ready"\nrunning = "running"\n'
        'review = "review"\nfailed = "failed"\nblocked = "blocked"\n'
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings = load_settings(cfg)
    assert settings.labels.ready == "ready"
    assert settings.labels.running == "running"


def test_load_settings_runtime_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[github]\nowner = "a"\nrepo = "b"\n[runtime]\ndry_run = true\n')
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings = load_settings(cfg)
    assert settings.runtime.dry_run is True
    assert settings.runtime.smoke_prompt is False
