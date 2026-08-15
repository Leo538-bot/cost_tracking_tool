"""Small in-process rate limiter for the login endpoint.

The shared group password is the only gate into a trip, so guessing must be slow.
State lives in memory: it resets on restart and does not span replicas, which is
fine for a single-container family-sized deployment.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()

WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS = 10

# The recovery key is the strongest secret in the system, so it gets a far
# tighter budget than an ordinary password typo.
RECOVERY_WINDOW_SECONDS = 60 * 60
RECOVERY_MAX_ATTEMPTS = 5


def check_and_record(
    key: str, *, max_attempts: int = MAX_ATTEMPTS, window_seconds: int = WINDOW_SECONDS
) -> tuple[bool, int]:
    """Register an attempt. Returns (allowed, seconds_until_retry)."""
    now = time.monotonic()
    with _LOCK:
        bucket = _ATTEMPTS[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()

        if len(bucket) >= max_attempts:
            return False, int(window_seconds - (now - bucket[0])) + 1

        bucket.append(now)
        return True, 0


def clear(key: str) -> None:
    """Drop the failure history after a successful login."""
    with _LOCK:
        _ATTEMPTS.pop(key, None)
