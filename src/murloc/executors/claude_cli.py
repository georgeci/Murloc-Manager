from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ExecResult


class ClaudeCliExecutor:
    def __init__(self, command: str = "claude", extra_args: list[str] | None = None) -> None:
        self.command = command
        self.extra_args = extra_args or []

    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult:
        cmd = [self.command, *self.extra_args, prompt]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            return ExecResult(
                ok=False,
                stdout=e.stdout or "",
                stderr=f"Claude CLI timeout after {timeout_sec}s",
                exit_code=124,
            )
        return ExecResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
