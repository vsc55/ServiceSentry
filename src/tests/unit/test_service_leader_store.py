#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ServiceLeaderStore — the single-owner leader lease (HA failover)."""

import time

from lib.db import get_connector
from lib.services.manager.leader import ServiceLeaderStore


def _store():
    db = get_connector(None, default_sqlite_path=':memory:')
    return ServiceLeaderStore(db), db


class TestServiceLeaderStore:

    def test_empty_has_no_leader(self):
        s, _ = _store()
        assert s.current_leader('monitoring') is None
        assert s.list_leaders() == []

    def test_acquire_then_others_blocked(self):
        s, _ = _store()
        assert s.try_acquire('monitoring', 'A', ttl=30) is True
        lead = s.current_leader('monitoring')
        assert lead and lead['instance_id'] == 'A'
        # Second contender cannot take a live lease.
        assert s.try_acquire('monitoring', 'B', ttl=30) is False
        assert s.current_leader('monitoring')['instance_id'] == 'A'

    def test_holder_can_renew(self):
        s, _ = _store()
        s.try_acquire('events', 'A', ttl=30)
        assert s.try_acquire('events', 'A', ttl=30) is True   # renew is idempotent

    def test_failover_after_expiry(self):
        s, db = _store()
        s.try_acquire('monitoring', 'A', ttl=30)
        # Force A's lease to have expired (A stopped renewing → crashed pod).
        db.execute("UPDATE service_leader SET expires_at = ? WHERE service_key='monitoring'",
                   (time.time() - 1,))
        db.commit()
        assert s.current_leader('monitoring') is None         # no live leader
        assert s.try_acquire('monitoring', 'B', ttl=30) is True
        assert s.current_leader('monitoring')['instance_id'] == 'B'

    def test_only_one_wins_an_expired_lease(self):
        s, db = _store()
        s.try_acquire('monitoring', 'A', ttl=30)
        db.execute("UPDATE service_leader SET expires_at = ? WHERE service_key='monitoring'",
                   (time.time() - 1,))
        db.commit()
        first = s.try_acquire('monitoring', 'B', ttl=30)
        second = s.try_acquire('monitoring', 'C', ttl=30)
        assert first is True and second is False              # B won, C blocked
        assert s.current_leader('monitoring')['instance_id'] == 'B'

    def test_release_enables_immediate_failover(self):
        s, _ = _store()
        s.try_acquire('events', 'A', ttl=30)
        s.release('events', 'A')
        assert s.current_leader('events') is None
        assert s.try_acquire('events', 'B', ttl=30) is True

    def test_release_by_non_holder_is_noop(self):
        s, _ = _store()
        s.try_acquire('events', 'A', ttl=30)
        s.release('events', 'B')                              # B isn't the holder
        assert s.current_leader('events')['instance_id'] == 'A'

    def test_keys_are_independent(self):
        s, _ = _store()
        assert s.try_acquire('monitoring', 'A', ttl=30) is True
        assert s.try_acquire('events', 'A', ttl=30) is True   # different lease
        assert {l['service_key'] for l in s.list_leaders()} == {'monitoring', 'events'}
