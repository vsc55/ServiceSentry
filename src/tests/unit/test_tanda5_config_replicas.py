#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Several processes on one config table: no replica may undo another's save.

Two ``ConfigManager``/``ConfigStore`` pairs on the same SQLite file stand in for two web
replicas (or a replica and the CLI).  Before the fix the cache was keyed only by an
in-process counter, so a replica never saw another's writes, and its next ``write()``
replaced the whole table from that stale copy — re-writing old values and deleting rows
the other replica had added.
"""

import pytest

from lib.db import get_connector
from lib.core.config.store import ConfigStore
from lib.config.manager import ConfigManager


@pytest.fixture()
def replicas(tmp_path):
    """``(make, fresh)`` — *make* builds a replica on the shared file; *fresh* reads the
    table as a brand-new process would."""
    db_path = str(tmp_path / 'shared.db')
    conns = []

    def make():
        # Each replica has its own config dir: a shared config.json would move every
        # replica's mtime on any save and hide whether the DB stamp is doing the work.
        db = get_connector(None, default_sqlite_path=db_path)
        conns.append(db)
        return ConfigManager(ConfigStore(db), str(tmp_path / f'config{len(conns)}.json'))

    def fresh():
        return make().read()

    seed = make()
    seed.write({'web_admin': {'lang': 'en_EN', 'theme': 'dark'},
                'modules': {'threads': 5}})
    yield make, fresh
    for db in conns:
        try:
            db.close()
        except Exception:  # pylint: disable=broad-except
            pass


def test_other_replica_change_survives_a_stale_write_of_another_key(replicas):
    make, fresh = replicas
    a, b = make(), make()
    a.STAMP_TTL = b.STAMP_TTL = 3600            # A never re-probes: its copy stays stale
    cfg_a = a.read()
    cfg_b = b.read()
    cfg_b['web_admin']['theme'] = 'light'
    assert b.write(cfg_b)
    cfg_a['modules']['threads'] = 9             # A edits a different key, from its old copy
    assert a.write(cfg_a)
    now = fresh()
    assert now['modules']['threads'] == 9
    assert now['web_admin']['theme'] == 'light'


def test_key_added_by_other_replica_is_not_deleted_by_a_stale_write(replicas):
    make, fresh = replicas
    a, b = make(), make()
    a.STAMP_TTL = 3600
    cfg_a = a.read()
    cfg_b = b.read()
    cfg_b.setdefault('syslog', {})['udp_port'] = 5514
    assert b.write(cfg_b)
    cfg_a['web_admin']['lang'] = 'es_ES'
    assert a.write(cfg_a)
    now = fresh()
    assert now['syslog']['udp_port'] == 5514
    assert now['web_admin']['lang'] == 'es_ES'


def test_key_deleted_by_other_replica_is_not_resurrected(replicas):
    make, fresh = replicas
    a, b = make(), make()
    a.STAMP_TTL = 3600
    cfg_a = a.read()
    cfg_b = b.read()
    del cfg_b['web_admin']['theme']
    assert b.write(cfg_b)
    cfg_a['modules']['threads'] = 7
    assert a.write(cfg_a)
    now = fresh()
    assert 'theme' not in now.get('web_admin', {})
    assert now['modules']['threads'] == 7


def test_caller_deletion_still_propagates(replicas):
    make, fresh = replicas
    a = make()
    cfg = a.read()
    del cfg['web_admin']['theme']
    assert a.write(cfg)
    assert 'theme' not in fresh().get('web_admin', {})


def test_replica_sees_other_replica_change_after_the_throttle(replicas):
    make, _fresh = replicas
    a, b = make(), make()
    a.STAMP_TTL = 3600
    assert a.read()['web_admin']['theme'] == 'dark'
    cfg_b = b.read()
    cfg_b['web_admin']['theme'] = 'light'
    assert b.write(cfg_b)
    # Inside the throttle window A answers from its cache, without asking the DB.
    assert a.read()['web_admin']['theme'] == 'dark'
    a.STAMP_TTL = 0                              # the window has elapsed
    assert a.read()['web_admin']['theme'] == 'light'


def test_stamp_is_probed_at_most_once_per_window(replicas):
    make, _fresh = replicas
    a = make()
    a.STAMP_TTL = 3600
    calls = []
    real = a._store.stamp

    def counting():
        calls.append(1)
        return real()

    a._store.stamp = counting
    for _ in range(20):
        a.read()
    assert len(calls) == 1


def test_own_write_is_visible_at_once_despite_the_throttle(replicas):
    make, _fresh = replicas
    a = make()
    a.STAMP_TTL = 3600
    cfg = a.read()
    cfg['modules']['threads'] = 11
    assert a.write(cfg)
    assert a.read()['modules']['threads'] == 11


def test_store_writes_move_the_cross_process_stamp(replicas):
    make, _fresh = replicas
    a, b = make(), make()
    before = b._store.stamp()
    a._store.set('web_admin|lang', 'fr_FR')
    after_set = b._store.stamp()
    assert after_set is not None and after_set[0] > before[0]
    a._store.delete('web_admin|lang')
    assert b._store.stamp()[0] > after_set[0]
