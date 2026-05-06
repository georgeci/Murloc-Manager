from __future__ import annotations

import pytest
from pydantic import ValidationError

from murloc.checks_runner import run_checks
from murloc.config import ChecksCfg


def test_checks_cfg_rejects_empty_commands() -> None:
    with pytest.raises(ValidationError):
        ChecksCfg(commands=[])


def test_checks_cfg_rejects_empty_argv() -> None:
    with pytest.raises(ValidationError):
        ChecksCfg(commands=[["ruff", "check", "."], []])


def test_run_checks_rejects_empty(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least one command"):
        run_checks([], tmp_path)
