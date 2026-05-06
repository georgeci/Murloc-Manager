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


class Executor(Protocol):
    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult: ...
