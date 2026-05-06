from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger
from .base import ExecResult

log = get_logger()

_TAIL_CHAR_LIMIT = 200_000
_QUEUE_POLL_SEC = 0.5


@dataclass
class _Telemetry:
    cost_usd: float | None = None
    usage: dict | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    session_id: str | None = None


def _parse_result_message(line: str) -> dict | None:
    """Return the JSON payload of a stream-json `result` message, or None.

    Lines that aren't JSON, aren't dicts, or aren't of type=result are ignored.
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        msg = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(msg, dict) and msg.get("type") == "result":
        return msg
    return None


def _extract_telemetry(payload: dict | None) -> _Telemetry:
    """Pull cost/usage fields out of a stream-json `result` payload."""
    t = _Telemetry()
    if not isinstance(payload, dict):
        return t
    raw_cost = payload.get("total_cost_usd")
    if isinstance(raw_cost, (int, float)):
        t.cost_usd = float(raw_cost)
    raw_usage = payload.get("usage")
    if isinstance(raw_usage, dict):
        t.usage = raw_usage
    raw_dur = payload.get("duration_ms")
    if isinstance(raw_dur, int):
        t.duration_ms = raw_dur
    raw_turns = payload.get("num_turns")
    if isinstance(raw_turns, int):
        t.num_turns = raw_turns
    raw_sid = payload.get("session_id")
    if isinstance(raw_sid, str):
        t.session_id = raw_sid
    return t


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


def _drain_stream(
    proc: subprocess.Popen,
    q: queue.Queue,
    deadline: float,
) -> tuple[bool, deque[str], dict | None]:
    """Pump the executor's stdout queue until EOF or the deadline lapses.

    Mirrors each line to stderr (live progress for the human watching) and
    keeps a bounded tail for failure reporting. Returns
    `(timed_out, tail, result_payload)` — `result_payload` is the most recent
    stream-json `result` message seen, or None if the run never emitted one.
    Killing the process on timeout is the caller's contract via the queue.
    """
    tail: deque[str] = deque()
    tail_size = 0
    result_payload: dict | None = None
    timed_out = False

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

        maybe_result = _parse_result_message(line)
        if maybe_result is not None:
            result_payload = maybe_result

    return timed_out, tail, result_payload


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

        timed_out, tail, result_payload = _drain_stream(
            proc, q, started + timeout_sec
        )

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)

        duration = round(time.monotonic() - started, 2)
        output = "".join(tail)
        t = _extract_telemetry(result_payload)

        if timed_out:
            log.warning(
                "claude_timeout",
                duration_sec=duration,
                timeout_sec=timeout_sec,
                cost_usd=t.cost_usd,
                num_turns=t.num_turns,
            )
            return ExecResult(
                ok=False,
                stdout=output,
                stderr=f"Claude CLI timeout after {timeout_sec}s",
                exit_code=124,
                cost_usd=t.cost_usd,
                usage=t.usage,
                duration_ms=t.duration_ms,
                num_turns=t.num_turns,
                session_id=t.session_id,
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        log.info(
            "claude_exit",
            exit_code=exit_code,
            duration_sec=duration,
            output_chars=len(output),
            cost_usd=t.cost_usd,
            num_turns=t.num_turns,
            session_id=t.session_id,
        )
        return ExecResult(
            ok=exit_code == 0,
            stdout=output,
            stderr="",
            exit_code=exit_code,
            cost_usd=t.cost_usd,
            usage=t.usage,
            duration_ms=t.duration_ms,
            num_turns=t.num_turns,
            session_id=t.session_id,
        )
