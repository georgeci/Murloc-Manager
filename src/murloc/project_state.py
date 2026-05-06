from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LabelMap:
    ready: str
    running: str
    review: str
    failed: str
    blocked: str

    def state_of(self, labels: list[str]) -> State:
        s = set(labels)
        if self.running in s:
            return State.RUNNING
        if self.review in s:
            return State.REVIEW
        if self.failed in s:
            return State.FAILED
        if self.blocked in s:
            return State.BLOCKED
        if self.ready in s:
            return State.READY
        return State.UNKNOWN

    def all_agent_labels(self) -> set[str]:
        return {self.ready, self.running, self.review, self.failed, self.blocked}
