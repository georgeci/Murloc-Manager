from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryPolicy:
    max_attempts: int

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts
