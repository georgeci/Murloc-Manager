from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ExecResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    # Per-invocation cost telemetry, populated when the executor speaks
    # `stream-json`. None means the executor did not report it (e.g. the user
    # forced a different `--output-format`, or the run died before the final
    # `result` message).
    cost_usd: float | None = None
    usage: dict | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    session_id: str | None = None


class Executor(Protocol):
    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult: ...
