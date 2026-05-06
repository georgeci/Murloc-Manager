from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from ..logging_setup import get_logger
from .base import ExecResult

log = get_logger()

_TAIL_CHAR_LIMIT = 200_000
_QUEUE_POLL_SEC = 0.5


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

        # Reader thread pushes lines into a queue so the main loop can enforce
        # the deadline even when the child stops emitting newlines.
        q: queue.Queue[str | None] = queue.Queue()

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    q.put(line)
            finally:
                q.put(None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        # Bounded tail: append every line, but cap total stored chars so a
        # very long agent run does not consume unbounded memory. The tail is
        # only used for failure reporting; live output is streamed straight
        # to stderr.
        tail: deque[str] = deque()
        tail_size = 0
        timed_out = False
        deadline = started + timeout_sec

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                proc.kill()
                break
            try:
                line = q.get(timeout=min(_QUEUE_POLL_SEC, max(remaining, 0.05)))
            except queue.Empty:
                continue
            if line is None:
                break
            sys.stderr.write(line)
            sys.stderr.flush()
            tail.append(line)
            tail_size += len(line)
            while tail and tail_size > _TAIL_CHAR_LIMIT:
                tail_size -= len(tail.popleft())

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)

        duration = round(time.monotonic() - started, 2)
        output = "".join(tail)

        if timed_out:
            log.warning("claude_timeout", duration_sec=duration, timeout_sec=timeout_sec)
            return ExecResult(
                ok=False,
                stdout=output,
                stderr=f"Claude CLI timeout after {timeout_sec}s",
                exit_code=124,
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        log.info(
            "claude_exit",
            exit_code=exit_code,
            duration_sec=duration,
            output_chars=len(output),
        )
        return ExecResult(
            ok=exit_code == 0,
            stdout=output,
            stderr="",
            exit_code=exit_code,
        )
