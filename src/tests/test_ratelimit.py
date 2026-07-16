#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the in-process sliding-window rate limiter (lib.security.ratelimit).

Anti-brute-force speed bump used on /login and the SCIM bearer endpoint. Uses a
controllable clock (monkeypatched ``ratelimit._time``) so window expiry and GC are
deterministic without real sleeps.
"""

import pytest

from lib.security import ratelimit
from lib.security.ratelimit import RateLimiter


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def time(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(ratelimit, '_time', c)
    return c


class TestRateLimiter:
    def test_under_limit_allowed(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            allowed, retry = rl.hit('ip', max_hits=3, window_secs=60)
            assert allowed is True
            assert retry == 0

    def test_exceeding_limit_blocked_with_retry(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            assert rl.hit('ip', 3, 60)[0] is True
        allowed, retry = rl.hit('ip', 3, 60)   # 4th within the window
        assert allowed is False
        assert retry >= 1

    def test_zero_max_disables_limit(self, clock):
        rl = RateLimiter()
        for _ in range(100):
            assert rl.hit('ip', 0, 60) == (True, 0)

    def test_window_slides(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            assert rl.hit('ip', 3, 60)[0] is True
        assert rl.hit('ip', 3, 60)[0] is False     # over the limit now
        clock.advance(61)                           # whole window elapses
        assert rl.hit('ip', 3, 60)[0] is True       # stale hits dropped → allowed again

    def test_keys_are_independent(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            rl.hit('a', 3, 60)
        assert rl.hit('a', 3, 60)[0] is False       # 'a' over
        assert rl.hit('b', 3, 60)[0] is True        # 'b' unaffected

    def test_peek_does_not_record(self, clock):
        rl = RateLimiter()
        for _ in range(10):
            assert rl.peek('ip', 3, 60)[0] is True  # peek never counts
        assert rl.hit('ip', 3, 60)[0] is True       # so the real first hit is allowed

    def test_peek_reports_over_after_hits(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            rl.hit('ip', 3, 60)
        allowed, retry = rl.peek('ip', 3, 60)
        assert allowed is False
        assert retry >= 1

    def test_reset_forgets_history(self, clock):
        rl = RateLimiter()
        for _ in range(3):
            rl.hit('ip', 3, 60)
        assert rl.hit('ip', 3, 60)[0] is False
        rl.reset('ip')
        assert rl.hit('ip', 3, 60)[0] is True

    def test_gc_drops_stale_buckets(self, clock):
        rl = RateLimiter()
        rl.hit('old', 5, 30)
        assert 'old' in rl._buckets
        clock.advance(200)                          # past the window + GC interval
        rl.hit('new', 5, 30)                         # this hit triggers _gc()
        assert 'old' not in rl._buckets              # stale bucket pruned
        assert 'new' in rl._buckets
