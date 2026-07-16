#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end HA leader-gating tests (multi-replica failover).

`test_service_leader_store.py` covers the lease store in isolation; this exercises
the *mixin-level* gating that the running services actually use — two
``_HeartbeatMixin`` replicas sharing one leader store — so a single-owner service
(monitor/events) runs on exactly one replica and fails over to a standby when the
holder stops renewing, while an active-active service (syslog) runs everywhere.
"""

import time

from lib.db import get_connector
from lib.services.manager.leader import ServiceLeaderStore
from lib.services.heartbeat import _HeartbeatMixin


class _Node(_HeartbeatMixin):
    """A minimal leader-gated service replica sharing a leader store (like the
    monitor/events embedded twins or their standalone services)."""

    _LEADER_GATED = True
    _HB_KEY = 'monitoring'
    _LEADER_TTL = 30

    def __init__(self, iid, store):
        self._hb_iid = iid                      # deterministic instance id
        self._service_leader_store = store

    def _hb_key(self):
        return self._HB_KEY


def _shared_store():
    """One in-memory DB shared by every replica (their common backing store)."""
    db = get_connector(None, default_sqlite_path=':memory:')
    return ServiceLeaderStore(db), db


class TestHaLeaderGating:
    def test_only_one_replica_is_leader(self):
        store, _ = _shared_store()
        a, b = _Node('A', store), _Node('B', store)
        a._renew_leadership()
        b._renew_leadership()
        assert a._work_allowed() is True          # A won the lease
        assert b._work_allowed() is False         # B is hot standby
        assert store.current_leader('monitoring')['instance_id'] == 'A'

    def test_failover_when_holder_stops_renewing(self):
        store, db = _shared_store()
        a, b = _Node('A', store), _Node('B', store)
        a._renew_leadership()
        assert a._work_allowed() is True
        # A crashes: it stops renewing, so its lease expires.
        db.execute("UPDATE service_leader SET expires_at=? WHERE service_key='monitoring'",
                   (time.time() - 1,))
        db.commit()
        b._renew_leadership()                     # standby claims the expired lease
        assert b._work_allowed() is True
        a._renew_leadership()                     # A comes back → no longer leader
        assert a._work_allowed() is False
        assert store.current_leader('monitoring')['instance_id'] == 'B'

    def test_clean_release_is_instant_failover(self):
        store, _ = _shared_store()
        a, b = _Node('A', store), _Node('B', store)
        a._renew_leadership()
        assert a._work_allowed() is True
        store.release('monitoring', a._hb_instance_id())   # clean shutdown
        b._renew_leadership()                              # takes over without TTL wait
        assert b._work_allowed() is True
        a._renew_leadership()
        assert a._work_allowed() is False

    def test_active_active_service_runs_on_every_replica(self):
        # A non-gated service (syslog behind a load balancer): every replica works,
        # no leader store involved.
        class _ActiveActive(_HeartbeatMixin):
            _LEADER_GATED = False
            _HB_KEY = 'syslog'

        n1, n2 = _ActiveActive(), _ActiveActive()
        n1._renew_leadership()
        n2._renew_leadership()
        assert n1._work_allowed() is True
        assert n2._work_allowed() is True

    def test_gated_without_store_defaults_to_sole_owner(self):
        # Embedded single-process case: leader-gated but no leader store wired →
        # behaves as the sole owner so nothing is silently gated off.
        node = _Node.__new__(_Node)
        node._hb_iid = 'solo'
        node._service_leader_store = None
        node._renew_leadership()
        assert node._work_allowed() is True
