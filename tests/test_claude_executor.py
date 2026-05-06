from __future__ import annotations

from murloc.executors.claude_cli import ClaudeCliExecutor, _ensure_stream_json


def test_injects_stream_json_when_user_did_not_specify() -> None:
    out = _ensure_stream_json(["--print", "--permission-mode=acceptEdits"])
    assert "--output-format" in out
    assert "stream-json" in out
    assert "--verbose" in out


def test_respects_user_chosen_output_format() -> None:
    out = _ensure_stream_json(["--print", "--output-format", "json"])
    # User picked their own format; we don't second-guess them.
    assert out.count("--output-format") == 1
    assert "stream-json" not in out


def test_respects_user_chosen_output_format_with_equals() -> None:
    out = _ensure_stream_json(["--print", "--output-format=text"])
    assert out.count("--output-format") == 0  # only the =text form
    assert any(a == "--output-format=text" for a in out)
    assert "stream-json" not in out


def test_constructor_normalises_extra_args() -> None:
    ex = ClaudeCliExecutor(extra_args=["--print"])
    assert "--output-format" in ex.extra_args
    assert "stream-json" in ex.extra_args
