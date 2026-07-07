#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ServiceInstancesStore — the heartbeat / observed-state registry."""

import time

from lib.db import get_connector
from lib.services.control.instances import ServiceInstancesStore


def _store():
    db = get_connector(None, default_sqlite_path=':memory:')
    return ServiceInstancesStore(db), db


class TestServiceInstancesStore:

    def test_empty(self):
        s, _ = _store()
        assert s.list_instances() == []
        assert s.list_for('monitoring') == []

    def test_heartbeat_insert_then_update(self):
        s, _ = _store()
        s.heartbeat('h1:1:monitoring', 'monitoring', mode='standalone',
                    running=True, host='h1', pid=1, version='x',
                    control_url='http://h1:8765', last_cycle_at=100.0,
                    detail={'interval': 60})
        rows = s.list_instances()
        assert len(rows) == 1
        r = rows[0]
        assert r['instance_id'] == 'h1:1:monitoring'
        assert r['service_key'] == 'monitoring'
        assert r['mode'] == 'standalone'
        assert r['running'] is True
        assert r['host'] == 'h1' and r['pid'] == 1
        assert r['control_url'] == 'http://h1:8765'
        assert r['detail'] == {'interval': 60}
        first_started = r['started_at']

        # A second heartbeat upserts the same row (started_at stays stable).
        s.heartbeat('h1:1:monitoring', 'monitoring', mode='standalone',
                    running=False, host='h1', pid=1, detail={'interval': 90})
        rows = s.list_instances()
        assert len(rows) == 1
        assert rows[0]['running'] is False
        assert rows[0]['detail'] == {'interval': 90}
        assert rows[0]['started_at'] == first_started

    def test_list_for_filters_by_service(self):
        s, _ = _store()
        s.heartbeat('a', 'monitoring', mode='standalone', running=True)
        s.heartbeat('b', 'syslog', mode='standalone', running=True)
        s.heartbeat('c', 'monitoring', mode='embedded', running=True)
        assert {r['instance_id'] for r in s.list_for('monitoring')} == {'a', 'c'}
        assert {r['instance_id'] for r in s.list_for('syslog')} == {'b'}

    def test_mark_down(self):
        s, _ = _store()
        s.heartbeat('a', 'events', mode='standalone', running=True)
        s.mark_down('a')
        assert s.list_for('events')[0]['running'] is False

    def test_clear_others_removes_same_host_restarts(self):
        s, _ = _store()
        # Two prior runs of the same embedded process (different PIDs) + a real
        # replica on another host + a different service on this host.
        s.heartbeat('moria:1:monitoring', 'monitoring', mode='embedded', running=True, host='moria', pid=1)
        s.heartbeat('moria:2:monitoring', 'monitoring', mode='embedded', running=True, host='moria', pid=2)
        s.heartbeat('moria:3:monitoring', 'monitoring', mode='embedded', running=True, host='moria', pid=3)
        s.heartbeat('rohan:9:monitoring', 'monitoring', mode='standalone', running=True, host='rohan', pid=9)
        s.heartbeat('moria:3:events', 'events', mode='embedded', running=True, host='moria', pid=3)
        removed = s.clear_others('monitoring', 'embedded', 'moria', 'moria:3:monitoring')
        assert removed == 2                                  # PIDs 1 and 2 dropped
        ids = {r['instance_id'] for r in s.list_instances()}
        assert ids == {'moria:3:monitoring', 'rohan:9:monitoring', 'moria:3:events'}

    def test_prune_drops_stale_rows(self):
        s, db = _store()
        s.heartbeat('old', 'monitoring', mode='standalone', running=True)
        # Backdate last_seen well beyond the prune cutoff.
        db.execute("UPDATE service_instances SET last_seen = ? WHERE instance_id = 'old'",
                   (time.time() - 10000,))
        db.commit()
        s.heartbeat('new', 'monitoring', mode='standalone', running=True)
        removed = s.prune(older_than_secs=3600)
        assert removed == 1
        assert {r['instance_id'] for r in s.list_instances()} == {'new'}
