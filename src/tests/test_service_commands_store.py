#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ServiceCommandsStore — the one-shot service command queue."""

import time

from lib.db import get_connector
from lib.services.control.commands import ServiceCommandsStore


def _store():
    db = get_connector(None, default_sqlite_path=':memory:')
    return ServiceCommandsStore(db), db


class TestServiceCommandsStore:

    def test_enqueue_and_list(self):
        s, _ = _store()
        cid = s.enqueue('monitoring', 'run_now', args={'x': 1}, created_by='alice')
        assert cid > 0
        rows = s.list_recent('monitoring')
        assert len(rows) == 1
        assert rows[0]['action'] == 'run_now'
        assert rows[0]['args'] == {'x': 1}
        assert rows[0]['created_by'] == 'alice'
        assert rows[0]['claimed_at'] is None
        assert rows[0]['done_at'] is None

    def test_claim_is_exclusive(self):
        s, _ = _store()
        s.enqueue('monitoring', 'reload')
        first = s.claim_next('monitoring', 'inst-A')
        assert first is not None and first['action'] == 'reload'
        # A second claimer gets nothing — the row is already taken.
        assert s.claim_next('monitoring', 'inst-B') is None

    def test_claim_filters_by_service(self):
        s, _ = _store()
        s.enqueue('syslog', 'reload')
        assert s.claim_next('monitoring', 'inst') is None
        assert s.claim_next('syslog', 'inst') is not None

    def test_complete_records_outcome(self):
        s, _ = _store()
        cid = s.enqueue('events', 'run_now')
        cmd = s.claim_next('events', 'inst')
        s.complete(cmd['id'], True, '3 processed')
        row = s.list_recent('events')[0]
        assert row['id'] == cid
        assert row['ok'] is True
        assert row['result'] == '3 processed'
        assert row['done_at'] is not None

    def test_fifo_order(self):
        s, _ = _store()
        s.enqueue('monitoring', 'reload')
        s.enqueue('monitoring', 'run_now')
        assert s.claim_next('monitoring', 'i')['action'] == 'reload'
        assert s.claim_next('monitoring', 'i')['action'] == 'run_now'

    def test_prune_drops_finished(self):
        s, db = _store()
        cid = s.enqueue('monitoring', 'reload')
        cmd = s.claim_next('monitoring', 'i')
        s.complete(cmd['id'], True, 'ok')
        db.execute('UPDATE service_commands SET done_at = ? WHERE id = ?',
                   (time.time() - 10000, cid))
        db.commit()
        s.enqueue('monitoring', 'run_now')          # pending, recent → kept
        removed = s.prune(older_than_secs=3600)
        assert removed == 1
        assert {r['action'] for r in s.list_recent('monitoring')} == {'run_now'}
