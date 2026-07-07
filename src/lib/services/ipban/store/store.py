#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``IpBanStore`` — the fail2ban persistence facade.

One class per table lives in its own module (``bans`` / ``offense_counters`` /
``offense_log`` / ``service_actions`` / ``history``); this facade composes them into
the single store handle the jail expects, and owns the few operations that span more
than one table (``clear_offenses`` = counters + log; ``prune`` = counters + log +
history).  :class:`lib.services.ipban.jail.IpBanManager` receives one of these and the
web routes reach it via ``wa._ipban_store``, so the public method surface is unchanged
by the per-table split.
"""

from __future__ import annotations

from lib.db import BaseConnector

from .bans import BansStore
from .history import BanHistoryStore
from .offense_counters import OffenseCountersStore
from .offense_log import OffenseLogStore
from .service_actions import ServiceActionStore


class IpBanStore:
    """Persistent, cross-process fail2ban state: jail + offense counters + log +
    per-service block actions + ban history, composed from one store per table."""

    def __init__(self, db: BaseConnector) -> None:
        self._bans = BansStore(db)
        self._counters = OffenseCountersStore(db)
        self._log = OffenseLogStore(db)
        self._svc = ServiceActionStore(db)
        self._history = BanHistoryStore(db)

    # ── ip_bans (the jail) ──────────────────────────────────────────────────────
    def upsert(self, ip: str, rec: dict) -> None:
        self._bans.upsert(ip, rec)

    def delete(self, ip: str) -> bool:
        return self._bans.delete(ip)

    def delete_by_uid(self, uid: str) -> str | None:
        return self._bans.delete_by_uid(uid)

    def load_active(self, now: float) -> list[dict]:
        return self._bans.load_active(now)

    def query(self, *, limit: int = 500) -> list[dict]:
        return self._bans.query(limit=limit)

    def get_ban(self, ip: str) -> dict | None:
        return self._bans.get_ban(ip)

    def active_bans(self, now: float) -> list[dict]:
        return self._bans.active_bans(now)

    # ── ip_offense_counters ─────────────────────────────────────────────────────
    def bump_offense(self, ip: str, track: str, now: float, window: float) -> int:
        return self._counters.bump_offense(ip, track, now, window)

    def counters(self) -> list[dict]:
        return self._counters.counters()

    def reset_counters(self, ip: str) -> None:
        self._counters.reset(ip)

    # ── ip_offense_log ──────────────────────────────────────────────────────────
    def log_attempt(self, ip: str, ts: float, category: str) -> None:
        self._log.log_attempt(ip, ts, category)

    def history(self, ip: str, *, limit: int = 200) -> list[dict]:
        return self._log.history(ip, limit=limit)

    # ── ip_service_action ───────────────────────────────────────────────────────
    def service_actions(self) -> dict:
        return self._svc.service_actions()

    def set_service_action(self, service: str, action: str) -> None:
        self._svc.set_service_action(service, action)

    # ── ip_ban_history ──────────────────────────────────────────────────────────
    def log_ban_event(self, ip: str, event: str, rec: dict, ts: float) -> None:
        self._history.log_ban_event(ip, event, rec, ts)

    def ban_history(self, *, limit: int = 500, ip: str | None = None) -> list[dict]:
        return self._history.ban_history(limit=limit, ip=ip)

    # ── cross-table operations ──────────────────────────────────────────────────
    def clear_offenses(self, ip: str) -> bool:
        """Forget an IP's counters + attempt log (watchlist removal). True if any existed."""
        if not ip:
            return False
        had = self._counters.clear(ip)
        self._log.clear(ip)
        return had

    def prune(self, now: float, *, max_age: float = 86400) -> None:
        """Housekeeping (called periodically): drop stale counters and trim the logs."""
        self._counters.prune_stale(now, max_age)
        self._log.trim()
        self._history.trim()


def create(db: BaseConnector) -> IpBanStore:
    return IpBanStore(db)
