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


def test_state_ready() -> None:
    assert LABELS.state_of(["agent:ready"]) == State.READY


def test_state_failed() -> None:
    assert LABELS.state_of(["agent:failed"]) == State.FAILED


def test_state_blocked() -> None:
    assert LABELS.state_of(["agent:blocked"]) == State.BLOCKED


def test_state_running_beats_review() -> None:
    assert LABELS.state_of(["agent:review", "agent:running"]) == State.RUNNING


def test_state_running_beats_ready() -> None:
    assert LABELS.state_of(["agent:ready", "agent:running"]) == State.RUNNING


def test_all_agent_labels() -> None:
    assert "agent:running" in LABELS.all_agent_labels()
    assert len(LABELS.all_agent_labels()) == 5


def test_all_agent_labels_contains_all_values() -> None:
    labels = LABELS.all_agent_labels()
    assert LABELS.ready in labels
    assert LABELS.running in labels
    assert LABELS.review in labels
    assert LABELS.failed in labels
    assert LABELS.blocked in labels
