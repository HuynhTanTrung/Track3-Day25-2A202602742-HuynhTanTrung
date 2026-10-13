"""Part A2 — Backoff with full jitter, and a retry budget."""

from __future__ import annotations

import random


class FullJitterBackoff:
    """Exponential backoff with *full* jitter (Brooker, AWS 2015)."""

    def __init__(self, base_s: float = 0.25, cap_s: float = 8.0, rng: random.Random | None = None) -> None:
        if base_s <= 0 or cap_s <= 0:
            raise ValueError("base_s and cap_s must be positive")
        self.base_s = base_s
        self.cap_s = cap_s
        self.rng = rng or random.Random(0)

    def delay(self, retry_number: int, retry_after: float | None = None) -> float:
        if retry_number < 1:
            raise ValueError("retry_number must be >= 1")

        # Honour the provider's retry-after: never come back earlier than it
        # told us, but add a small jitter on top so all clients don't stampede
        # back at the same instant.
        if retry_after is not None:
            return retry_after + self.rng.uniform(0, self.base_s)

        # Full jitter: uniform(0, min(cap, base * 2**(n-1))).
        ceiling = min(self.cap_s, self.base_s * (2 ** (retry_number - 1)))
        return self.rng.uniform(0, ceiling)


class RetryBudget:
    """Token-bucket retry budget (as in Finagle / gRPC retry throttling)."""

    def __init__(self, ratio: float = 0.1, min_per_s: float = 0.5, max_tokens: float = 20.0) -> None:
        self.ratio = ratio
        self.min_per_s = min_per_s
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self._last: float | None = None  # virtual time of the previous call

    def _refill(self, now: float) -> None:
        """Refill by elapsed virtual time, then remember the new timestamp."""
        if self._last is None:
            self._last = now
            return
        elapsed = max(0.0, now - self._last)
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.min_per_s)
        self._last = now

    def record_request(self, now: float) -> None:
        """A first attempt happened: refill, then deposit `ratio` tokens."""
        self._refill(now)
        self.tokens = min(self.max_tokens, self.tokens + self.ratio)

    def try_acquire_retry(self, now: float) -> bool:
        """A retry is requested: refill, then take one token if available."""
        self._refill(now)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False