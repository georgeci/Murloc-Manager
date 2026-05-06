from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from ..logging_setup import get_logger
from .base import ExecResult

log = get_logger()


class ClaudeCliExecutor:
    def __init__(self, command: str = "claude", extra_args: list[str] | None = None) -> None:
        self.command = command
        self.extra_args = extra_args or []

    def run(self, prompt: str, cwd: Path, timeout_sec: int) -> ExecResult:
        cmd = [self.command, *self.extra_args, prompt]
        log.info(
            "claude_start",
            command=self.command,
            extra_args=self.extra_args,
            cwd=str(cwd),
            timeout_sec=timeout_sec,
            prompt_chars=len(prompt),
        )
        started = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        chunks: list[str] = []
        deadline = started + timeout_sec
        timed_out = False
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                chunks.append(line)
                if time.monotonic() > deadline:
                    timed_out = True
                    proc.kill()
                    break
        finally:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        duration = round(time.monotonic() - started, 2)
        output = "".join(chunks)

        if timed_out:
            log.warning("claude_timeout", duration_sec=duration, timeout_sec=timeout_sec)
            return ExecResult(
                ok=False,
                stdout=output,
                stderr=f"Claude CLI timeout after {timeout_sec}s",
                exit_code=124,
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        log.info("claude_exit", exit_code=exit_code, duration_sec=duration, output_chars=len(output))
        return ExecResult(
            ok=exit_code == 0,
            stdout=output,
            stderr="",
            exit_code=exit_code,
        )
