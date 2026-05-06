from __future__ import annotations

from murloc.project_state import LabelMap, State

LABELS = LabelMap(
    ready="agent:ready",
    running="agent:running",
    review="agent:review",
    failed="agent:failed",
    blocked="agent:blocked",
)


def test_state_priority_running_over_ready() -> None:
    assert LABELS.state_of(["agent:ready", "agent:running"]) == State.RUNNING


def test_state_review() -> None:
    assert LABELS.state_of(["agent:review", "bug"]) == State.REVIEW


def test_state_unknown_for_no_agent_labels() -> None:
    assert LABELS.state_of(["bug", "feature"]) == State.UNKNOWN


def test_all_agent_labels() -> None:
    assert "agent:running" in LABELS.all_agent_labels()
    assert len(LABELS.all_agent_labels()) == 5
