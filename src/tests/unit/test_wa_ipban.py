#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internal fail2ban: IpBanManager unit tests + WebAdmin/store integration."""

import time

from lib.services.ipban.jail import IpBanManager
from tests.conftest import _login


def _mgr_on(store, **cfg):
    m = IpBanManager(store=store)
    base = dict(enabled=True, auth_threshold=5, auth_window=600,
                authz_threshold=30, authz_window=600, durations=[900])
    base.update(cfg)
    m.configure(**base)
    return m




# ──────────────────────────────────────────────────────────────────────────────
# Core manager
# ──────────────────────────────────────────────────────────────────────────────
class TestIpBanManager:
    def _mgr(self, **cfg):
        m = IpBanManager()
        base = dict(enabled=True, auth_threshold=3, auth_window=600,
                    authz_threshold=5, authz_window=600, durations=[10, 20, 30],
                    permanent_after=3)
        base.update(cfg)
        m.configure(**base)
        return m

    def test_auth_track_bans_at_threshold(self):
        m = self._mgr()
        ip = "203.0.113.5"
        assert not m.is_banned(ip)[0]
        for _ in range(2):
            m.register_offense(ip, "login_failed")
        assert not m.is_banned(ip)[0]         # below threshold (3)
        m.register_offense(ip, "login_failed")
        assert m.is_banned(ip)[0]             # threshold reached → jailed

    def test_authz_track_more_tolerant(self):
        m = self._mgr()
        ip = "198.51.100.9"
        for _ in range(4):                    # authz threshold is 5
            m.register_offense(ip, "forbidden")
        assert not m.is_banned(ip)[0]
        m.register_offense(ip, "forbidden")
        assert m.is_banned(ip)[0]

    def test_escalation_to_permanent(self):
        m = self._mgr()
        ip = "203.0.113.7"
        levels = []
        for _ in range(4):                    # 4 bans: 10s, 20s, 30s, then permanent
            for _ in range(3):
                m.register_offense(ip, "login_failed")
            levels.append(m.list_bans()[0]["permanent"])
        assert levels == [False, False, False, True]

    def test_whitelist_never_bans(self):
        m = self._mgr(extra_whitelist=["10.0.0.0/8"])
        ip = "10.1.2.3"
        for _ in range(10):
            m.register_offense(ip, "login_failed")
        assert not m.is_banned(ip)[0]
        assert m.ban(ip, duration_secs=60) is None      # explicit ban refused too

    def test_loopback_always_whitelisted(self):
        m = self._mgr()
        for _ in range(10):
            m.register_offense("127.0.0.1", "login_failed")
        assert not m.is_banned("127.0.0.1")[0]

    def test_manual_ban_and_unban(self):
        m = self._mgr()
        ip = "192.0.2.50"
        rec = m.ban(ip, duration_secs=0, reason="manual")   # 0 ⇒ permanent
        assert rec and rec["until"] is None
        assert m.is_banned(ip)[0]
        assert m.unban(ip) is True
        assert not m.is_banned(ip)[0]
        assert m.unban(ip) is False                          # already gone

    def test_watchlist_lists_pending_offenders(self):
        m = self._mgr()                       # auth threshold 3, authz 5
        for _ in range(2):
            m.register_offense("203.0.113.30", "login_failed")
        for _ in range(4):
            m.register_offense("198.51.100.40", "forbidden")
        watch = {o["ip"]: o for o in m.list_offenders()}
        assert watch["203.0.113.30"]["total"] == 2
        assert watch["203.0.113.30"]["remaining"] == 1      # 3 - 2
        assert watch["198.51.100.40"]["remaining"] == 1      # 5 - 4
        # Closest-to-ban is sorted first.
        assert m.list_offenders()[0]["remaining"] == 1

    def test_banned_ip_leaves_watchlist(self):
        m = self._mgr()                       # threshold 3
        for _ in range(3):                    # reaches threshold → banned
            m.register_offense("203.0.113.31", "login_failed")
        assert m.is_banned("203.0.113.31")[0]
        assert "203.0.113.31" not in {o["ip"] for o in m.list_offenders()}

    def test_whitelisted_never_in_watchlist(self):
        m = self._mgr(extra_whitelist=["10.0.0.0/8"])
        for _ in range(2):
            m.register_offense("10.1.2.3", "login_failed")
        assert m.list_offenders() == []

    def test_disabled_never_blocks(self):
        m = self._mgr(enabled=False)
        m.ban("203.0.113.1", duration_secs=60)               # ban recorded…
        assert not m.is_banned("203.0.113.1")[0]             # …but disabled ⇒ inert

    def test_expired_ban_stops_blocking(self):
        m = self._mgr(durations=[1])
        ip = "203.0.113.9"
        for _ in range(3):
            m.register_offense(ip, "login_failed")
        assert m.is_banned(ip)[0]
        time.sleep(1.1)
        assert not m.is_banned(ip)[0]


# ──────────────────────────────────────────────────────────────────────────────
# Persistent store round-trip
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# WebAdmin integration (gate + offense capture + API)
# ──────────────────────────────────────────────────────────────────────────────


