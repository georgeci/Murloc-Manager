from __future__ import annotations

import json
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


def _ensure_stream_json(extra_args: list[str]) -> list[str]:
    """Inject `--output-format stream-json --verbose` unless the user
    already chose an output format. stream-json is what gives us per-run
    cost/usage telemetry; --verbose is required by the CLI when streaming.
    """
    has_format = any(
        a == "--output-format" or a.startswith("--output-format=") for a in extra_args
    )
    if has_format:
        return list(extra_args)
    out = list(extra_args)
    out += ["--output-format", "stream-json", "--verbose"]
    return out


class ClaudeCliExecutor:
    def __init__(self, command: str = "claude", extra_args: list[str] | None = None) -> None:
        self.command = command
        self.extra_args = _ensure_stream_json(extra_args or [])

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

        # Telemetry from the final `result` message in stream-json output.
        result_payload: dict | None = None

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

            stripped = line.strip()
            if stripped.startswith("{"):
                try:
                    msg = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(msg, dict) and msg.get("type") == "result":
                        result_payload = msg

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)

        duration = round(time.monotonic() - started, 2)
        output = "".join(tail)

        cost_usd: float | None = None
        usage: dict | None = None
        duration_ms: int | None = None
        num_turns: int | None = None
        session_id: str | None = None
        if isinstance(result_payload, dict):
            raw_cost = result_payload.get("total_cost_usd")
            if isinstance(raw_cost, (int, float)):
                cost_usd = float(raw_cost)
            raw_usage = result_payload.get("usage")
            if isinstance(raw_usage, dict):
                usage = raw_usage
            raw_dur = result_payload.get("duration_ms")
            if isinstance(raw_dur, int):
                duration_ms = raw_dur
            raw_turns = result_payload.get("num_turns")
            if isinstance(raw_turns, int):
                num_turns = raw_turns
            raw_sid = result_payload.get("session_id")
            if isinstance(raw_sid, str):
                session_id = raw_sid

        if timed_out:
            log.warning(
                "claude_timeout",
                duration_sec=duration,
                timeout_sec=timeout_sec,
                cost_usd=cost_usd,
                num_turns=num_turns,
            )
            return ExecResult(
                ok=False,
                stdout=output,
                stderr=f"Claude CLI timeout after {timeout_sec}s",
                exit_code=124,
                cost_usd=cost_usd,
                usage=usage,
                duration_ms=duration_ms,
                num_turns=num_turns,
                session_id=session_id,
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        log.info(
            "claude_exit",
            exit_code=exit_code,
            duration_sec=duration,
            output_chars=len(output),
            cost_usd=cost_usd,
            num_turns=num_turns,
            session_id=session_id,
        )
        return ExecResult(
            ok=exit_code == 0,
            stdout=output,
            stderr="",
            exit_code=exit_code,
            cost_usd=cost_usd,
            usage=usage,
            duration_ms=duration_ms,
            num_turns=num_turns,
            session_id=session_id,
        )
