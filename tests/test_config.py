from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from murloc.config import _resolve_token, load_settings


class TestResolveToken:
    def test_empty_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert _resolve_token() == ""

    def test_whitespace_only_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "   ")
        assert _resolve_token() == ""

    def test_valid_ghp_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc123")
        assert _resolve_token() == "ghp_abc123"

    def test_all_valid_prefixes_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for prefix in ("ghp_", "gho_", "ghs_", "ghu_", "ghr_", "github_pat_"):
            monkeypatch.setenv("GITHUB_TOKEN", f"{prefix}abc123")
            assert _resolve_token() != "", f"expected {prefix} to be accepted"

    def test_invalid_prefix_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "sk-invalid-token")
        assert _resolve_token() == ""

    def test_placeholder_your_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_your_token_here")
        assert _resolve_token() == ""

    def test_placeholder_your_dash_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_your-token")
        assert _resolve_token() == ""


class TestLoadSettings:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="config.toml"):
            load_settings(tmp_path / "config.toml")

    def test_valid_minimal_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[github]\nowner = "myorg"\nrepo = "myrepo"\n')
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        settings = load_settings(cfg)
        assert settings.github.owner == "myorg"
        assert settings.github.repo == "myrepo"
        assert settings.github.base_branch == "main"

    def test_defaults_applied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[github]\nowner = "o"\nrepo = "r"\n')
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        settings = load_settings(cfg)
        assert settings.labels.ready == "agent:ready"
        assert settings.executor.kind == "claude_cli"
        assert settings.runtime.dry_run is False

    def test_token_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[github]\nowner = "o"\nrepo = "r"\n')
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_testtoken")
        settings = load_settings(cfg)
        assert settings.github_token == "ghp_testtoken"
