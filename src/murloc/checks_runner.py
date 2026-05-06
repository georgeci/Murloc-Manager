from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    ok: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int


def run_checks(commands: list[list[str]], cwd: Path) -> CheckResult:
    """Run check commands sequentially. Returns first failure, or last success."""
    last: CheckResult | None = None
    for cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        last = CheckResult(
            ok=proc.returncode == 0,
            command=" ".join(cmd),
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
        if not last.ok:
            return last
    assert last is not None, "checks_runner called with empty commands"
    return last
