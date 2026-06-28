from collections import defaultdict
from time import time

class RateLimiter:
    """Sliding-window in-memory rate limiter. Thread-safe for single-process use."""

    def __init__(self):
        self._log: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_calls: int = 1, window_seconds: int = 60) -> bool:
        now = time()
        cutoff = now - window_seconds
        calls = [t for t in self._log[key] if t > cutoff]
        self._log[key] = calls
        if len(calls) >= max_calls:
            return False
        self._log[key].append(now)
        return True

    def seconds_until_next(self, key: str, window_seconds: int = 60) -> int:
        if not self._log[key]:
            return 0
        oldest = min(self._log[key])
        wait = window_seconds - (time() - oldest)
        return max(0, int(wait))


limiter = RateLimiter()
