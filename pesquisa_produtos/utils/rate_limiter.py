"""Token bucket rate limiter para respeitar limites das APIs."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Limita chamadas a `requests_per_second` por segundo usando token bucket."""

    def __init__(self, requests_per_second: float = 2.0) -> None:
        self.rate = requests_per_second
        self.tokens = requests_per_second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self._last_refill = now

            if self.tokens < 1:
                sleep_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(sleep_time)
                self.tokens = 0
            else:
                self.tokens -= 1
