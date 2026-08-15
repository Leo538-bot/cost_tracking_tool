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


def check_and_record(key: str) -> tuple[bool, int]:
    """Register an attempt. Returns (allowed, seconds_until_retry)."""
    now = time.monotonic()
    with _LOCK:
        bucket = _ATTEMPTS[key]
        while bucket and now - bucket[0] > WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= MAX_ATTEMPTS:
            return False, int(WINDOW_SECONDS - (now - bucket[0])) + 1

        bucket.append(now)
        return True, 0


def clear(key: str) -> None:
    """Drop the failure history after a successful login."""
    with _LOCK:
        _ATTEMPTS.pop(key, None)
