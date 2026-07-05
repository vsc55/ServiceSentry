#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-process sliding-window rate limiter.

Thread-safe, dependency-free.  Keyed by an arbitrary string (typically a client
IP): records a hit and reports whether the caller has exceeded ``max_hits`` within
the trailing ``window_secs``.  Used to throttle brute force against /login and the
SCIM bearer endpoint without pulling in Flask-Limiter/Redis."""

from __future__ import annotations

import threading
import time as _time
from collections import deque


class RateLimiter:
    """Fixed set of independent sliding-window counters keyed by string.

    Not persistent (counters reset on restart) and per-process (each worker keeps
    its own) — adequate as a brute-force speed bump layered on top of the durable
    per-account lockout, not a distributed quota.
    """

    def __init__(self):
        self._buckets: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_gc = 0.0

    def hit(self, key: str, max_hits: int, window_secs: float) -> tuple[bool, int]:
        """Record a hit for *key*; return ``(allowed, retry_after_secs)``.

        ``allowed`` is False when this hit takes the trailing-window count past
        ``max_hits`` — the caller should then reject with 429 and ``Retry-After``.
        ``max_hits <= 0`` disables the limit (always allowed)."""
        if max_hits <= 0:
            return True, 0
        now = _time.time()
        cutoff = now - window_secs
        with self._lock:
            self._gc(now, window_secs)
            dq = self._buckets.get(key)
            if dq is None:
                dq = self._buckets[key] = deque()
            while dq and dq[0] <= cutoff:
                dq.popleft()
            dq.append(now)
            if len(dq) > max_hits:
                retry = int(dq[0] + window_secs - now) + 1
                return False, max(1, retry)
            return True, 0

    def peek(self, key: str, max_hits: int, window_secs: float) -> tuple[bool, int]:
        """Check whether *key* is already over the limit WITHOUT recording a hit —
        use to reject before doing work, then :meth:`hit` only on the events you
        actually want to count (e.g. failed logins)."""
        if max_hits <= 0:
            return True, 0
        now = _time.time()
        cutoff = now - window_secs
        with self._lock:
            dq = self._buckets.get(key)
            if not dq:
                return True, 0
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= max_hits:
                return False, max(1, int(dq[0] + window_secs - now) + 1)
            return True, 0

    def reset(self, key: str) -> None:
        """Forget a key's history (e.g. after a successful login)."""
        with self._lock:
            self._buckets.pop(key, None)

    def _gc(self, now: float, window_secs: float) -> None:
        # Occasionally drop stale buckets so a rotating-IP attacker can't grow the
        # map without bound. Called under the lock.
        if now - self._last_gc < max(60.0, window_secs):
            return
        self._last_gc = now
        cutoff = now - window_secs
        for k in [k for k, dq in self._buckets.items() if not dq or dq[-1] <= cutoff]:
            self._buckets.pop(k, None)
