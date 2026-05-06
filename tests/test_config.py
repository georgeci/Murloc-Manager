from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murloc.config import (
    _detect_github_owner_repo,
    _parse_github_url,
    _resolve_token,
    load_settings,
)


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

    def test_auto_detect_owner_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("[github]\n")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_OWNER", raising=False)
        monkeypatch.delenv("GITHUB_REPO", raising=False)

        def _fake_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args, returncode=0, stdout="https://github.com/alice/myrepo\n", stderr=""
            )

        monkeypatch.setattr("murloc.config.subprocess.run", _fake_run)
        settings = load_settings(cfg)
        assert settings.github.owner == "alice"
        assert settings.github.repo == "myrepo"

    def test_explicit_config_overrides_auto_detect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text('[github]\nowner = "myorg"\nrepo = "myrepo"\n')
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        def _fail(*_args, **_kwargs):
            pytest.fail("auto-detect must not run when config provides owner/repo")

        monkeypatch.setattr("murloc.config._detect_github_owner_repo", _fail)
        settings = load_settings(cfg)
        assert settings.github.owner == "myorg"
        assert settings.github.repo == "myrepo"

    def test_env_overrides_auto_detect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = tmp_path / "config.toml"
        cfg.write_text("[github]\n")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_OWNER", "envowner")
        monkeypatch.setenv("GITHUB_REPO", "envrepo")

        def _fail(*_args, **_kwargs):
            pytest.fail("auto-detect must not run when env vars supply owner/repo")

        monkeypatch.setattr("murloc.config._detect_github_owner_repo", _fail)
        settings = load_settings(cfg)
        assert settings.github.owner == "envowner"
        assert settings.github.repo == "envrepo"


class TestParseGithubUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://github.com/alice/myrepo", ("alice", "myrepo")),
            ("https://github.com/alice/myrepo.git", ("alice", "myrepo")),
            ("git@github.com:alice/myrepo", ("alice", "myrepo")),
            ("git@github.com:alice/myrepo.git", ("alice", "myrepo")),
            ("ssh://git@github.com/alice/myrepo", ("alice", "myrepo")),
            ("ssh://git@github.com/alice/myrepo.git", ("alice", "myrepo")),
        ],
    )
    def test_valid_urls(self, url: str, expected: tuple[str, str]) -> None:
        assert _parse_github_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/alice/myrepo",
            "git@bitbucket.org:alice/myrepo",
            "not-a-url",
            "",
        ],
    )
    def test_non_github_urls_return_none(self, url: str) -> None:
        assert _parse_github_url(url) is None


class TestDetectGithubOwnerRepo:
    def _fake_run(self, returncode: int, stdout: str, stderr: str = ""):
        def inner(args, **kwargs):
            return subprocess.CompletedProcess(
                args, returncode=returncode, stdout=stdout, stderr=stderr
            )

        return inner

    def test_success_https(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(0, "https://github.com/alice/myrepo\n"),
        )
        assert _detect_github_owner_repo(str(tmp_path)) == ("alice", "myrepo")

    def test_success_git_at(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(0, "git@github.com:alice/myrepo.git\n"),
        )
        assert _detect_github_owner_repo(str(tmp_path)) == ("alice", "myrepo")

    def test_not_a_git_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(128, "", "fatal: not a git repository"),
        )
        with pytest.raises(ValueError, match="not a git repository"):
            _detect_github_owner_repo(str(tmp_path))

    def test_no_origin_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(2, "", "error: No such remote 'origin'"),
        )
        with pytest.raises(ValueError, match="git remote 'origin' is not configured"):
            _detect_github_owner_repo(str(tmp_path))

    def test_non_github_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(0, "https://gitlab.com/alice/myrepo\n"),
        )
        with pytest.raises(ValueError, match="not a GitHub URL"):
            _detect_github_owner_repo(str(tmp_path))

    def test_git_not_installed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args, **_kwargs):
            raise FileNotFoundError(2, "No such file or directory: 'git'")

        monkeypatch.setattr("murloc.config.subprocess.run", _raise)
        with pytest.raises(ValueError, match="git executable not found"):
            _detect_github_owner_repo(str(tmp_path))

    def test_subprocess_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs.get("timeout", 5))

        monkeypatch.setattr("murloc.config.subprocess.run", _raise)
        with pytest.raises(ValueError, match="timed out"):
            _detect_github_owner_repo(str(tmp_path))

    def test_unknown_git_failure_surfaces_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "murloc.config.subprocess.run",
            self._fake_run(1, "", "fatal: some other git error"),
        )
        with pytest.raises(ValueError, match="some other git error"):
            _detect_github_owner_repo(str(tmp_path))
