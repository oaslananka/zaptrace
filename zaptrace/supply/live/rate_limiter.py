"""Token bucket rate limiter for distributor API clients."""

from __future__ import annotations

import threading
import time


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter.

    Allows up to *capacity* requests in a burst, refilling at *rate* tokens/sec.
    """

    def __init__(self, rate: float = 2.0, capacity: float = 10.0) -> None:
        self.rate = max(0.1, rate)
        self.capacity = max(1.0, capacity)
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, tokens: float = 1.0, block: bool = True, timeout: float = 5.0) -> bool:
        """Acquire tokens, optionally blocking until available."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                if not block:
                    return False
                needed = tokens - self.tokens
                wait_time = needed / self.rate

            if time.monotonic() + wait_time > deadline:
                return False
            time.sleep(min(wait_time, 0.1))
