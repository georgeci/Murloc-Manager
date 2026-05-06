from __future__ import annotations

from murloc.orchestrator import Orchestrator, _redact_paths


def test_redact_paths_replaces_home(monkeypatch: None) -> None:
    import pathlib
    home = str(pathlib.Path.home())
    text = f"error in {home}/project/file.py"
    result = _redact_paths(text)
    assert home not in result
    assert "~" in result


def test_redact_paths_replaces_users_path() -> None:
    text = "File at /Users/alice/dev/proj/main.py line 5"
    result = _redact_paths(text)
    assert "alice" not in result
    assert "/Users/<redacted>" in result


def test_redact_paths_replaces_home_path() -> None:
    text = "traceback: /home/bob/code/app.py"
    result = _redact_paths(text)
    assert "bob" not in result
    assert "/home/<redacted>" in result


def test_redact_paths_leaves_other_text_unchanged() -> None:
    text = "No paths here, just a message."
    assert _redact_paths(text) == text


def test_compose_pr_body_with_agent_body() -> None:
    body = Orchestrator._compose_pr_body("Added the thing.", 7, 2)
    assert "Added the thing." in body
    assert "Resolves #7" in body
    assert "2 commit(s)" in body


def test_compose_pr_body_without_agent_body() -> None:
    body = Orchestrator._compose_pr_body("", 9, 1)
    assert "Resolves #9" in body
    assert "1 commit(s)" in body


def test_compose_pr_body_whitespace_only_agent_body() -> None:
    body = Orchestrator._compose_pr_body("   \n  ", 3, 1)
    assert "Resolves #3" in body
    assert "   \n  " not in body


def test_compose_pr_body_multiline_agent_body() -> None:
    agent = "Line 1.\n\nLine 2."
    body = Orchestrator._compose_pr_body(agent, 5, 3)
    assert "Line 1." in body
    assert "Line 2." in body
    assert "Resolves #5" in body
