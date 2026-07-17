"""Live multi-engine portability tests — run the stores against a REAL MySQL/MariaDB and/or
PostgreSQL, catching dialect breakages the SQLite suite can't (reserved-word identifiers,
CAST targets, UPDATE rowcount semantics, …).

Opt-in via environment variables (skipped entirely when unset — CI runs them only when a
scratch DB is provided; **never** hardcode credentials here):

    MySQL/MariaDB:   SS_TEST_MYSQL_HOST  [SS_TEST_MYSQL_PORT=3306]  SS_TEST_MYSQL_DB=test
                     SS_TEST_MYSQL_USER  SS_TEST_MYSQL_PASSWORD
    PostgreSQL:      SS_TEST_PG_HOST     [SS_TEST_PG_PORT=5432]     SS_TEST_PG_DB=test
                     SS_TEST_PG_USER     SS_TEST_PG_PASSWORD

The target database must be a SCRATCH database: these tests CREATE and DROP the store tables
(check_state/history/hosts/groups/groups_roles/audit/event_cursor/event_cooldowns). Run them
SERIALLY (``-n0``) — they use fixed table names, so parallel workers would collide.

The connection variables are conveniently kept in a gitignored ``tests/.env.test`` (auto-loaded
by ``conftest.py`` for the whole suite); see docs/ref-tests.md §81. Then just:

    .venv/Scripts/python -m pytest -n0 -q tests/test_db_portability_live.py
"""
import os
import time

import pytest

from lib.db import get_connector

_STORE_TABLES = ('check_state', 'history', 'hosts', 'groups', 'groups_roles', 'audit',
                 'event_cursor', 'event_cooldowns', 'service_leader',
                 'ss_deftest', '__ssreb_ss_deftest', '__ssbak_ss_deftest')


def _mysql_cfg():
    host = os.environ.get('SS_TEST_MYSQL_HOST')
    if not host:
        return None
    return {'driver': 'mysql', 'host': host,
            'name': os.environ.get('SS_TEST_MYSQL_DB', 'test'),
            'user': os.environ.get('SS_TEST_MYSQL_USER', 'root'),
            'password': os.environ.get('SS_TEST_MYSQL_PASSWORD', ''),
            'port': int(os.environ.get('SS_TEST_MYSQL_PORT', '3306'))}


def _pg_cfg():
    host = os.environ.get('SS_TEST_PG_HOST')
    if not host:
        return None
    return {'driver': 'postgresql', 'host': host,
            'name': os.environ.get('SS_TEST_PG_DB', 'test'),
            'user': os.environ.get('SS_TEST_PG_USER', 'postgres'),
            'password': os.environ.get('SS_TEST_PG_PASSWORD', ''),
            'port': int(os.environ.get('SS_TEST_PG_PORT', '5432'))}


def _drop_all(db):
    for t in _STORE_TABLES:
        try:
            db.execute(f'DROP TABLE IF EXISTS {db.quote_ident(t)}')
            db.commit()
        except Exception:  # pylint: disable=broad-except
            pass


@pytest.fixture(params=['mysql', 'postgresql'])
def live_db(request):
    """A real connector for each configured engine; skips the engine when unset."""
    # These tests use fixed table names and drop/recreate them, so they must not run in
    # parallel (xdist workers would clobber each other). Under `-n auto` they'd now be
    # collected — since `.env.test` is auto-loaded for the whole suite — so skip unless
    # serial. Run them with `-n0` (see docs/ref-tests.md §81).
    if int(os.environ.get('PYTEST_XDIST_WORKER_COUNT', '1')) > 1:
        pytest.skip('live DB tests must run serially - use -n0')
    cfg = _mysql_cfg() if request.param == 'mysql' else _pg_cfg()
    if cfg is None:
        var = 'SS_TEST_MYSQL_HOST' if request.param == 'mysql' else 'SS_TEST_PG_HOST'
        pytest.skip(f'{request.param} not configured (set {var})')
    try:
        db = get_connector(cfg)
        db.fetchone('SELECT 1')          # fail fast if unreachable
    except Exception as exc:  # pylint: disable=broad-except
        pytest.skip(f'{request.param} unreachable: {exc}')
    _drop_all(db)                        # clean slate
    yield db
    _drop_all(db)                        # tidy up


# ── the operations that were broken on MySQL/PostgreSQL before the quoting sweep ──

def test_hosts_virtual_roundtrip(live_db):
    from lib.core.hosts.store import HostsStore
    s = HostsStore(live_db)
    uid = s.create({'name': 'live-h1', 'address': '10.0.0.1', 'virtual': True}, actor='test')
    assert uid and any(h['uid'] == uid for h in s.list())
    assert s.get(uid)['virtual'] is True
    s.update(uid, {'name': 'live-h1', 'address': '10.0.0.2', 'virtual': False}, actor='test')
    assert s.get(uid)['virtual'] is False


def test_history_key_cast_json(live_db):
    from lib.core.history.store import HistoryStore
    s = HistoryStore(live_db)
    for i in range(60):
        s.record('livemod', 'livekey', status=(i % 2 == 0), data={'v': i})
    assert any(r.get('key') == 'livekey' for r in s.get_index())
    assert s.query('livemod', 'livekey', 0, time.time() + 1, max_points=5)     # bucketed CAST
    assert s.get_stats('livemod', 'livekey', 0, time.time() + 1, field='v').get('count')
    # a non-numeric field value must NOT lose the basic stats (PostgreSQL's numeric CAST raises;
    # SQLite/MySQL degrade to NULL) — the field aggregates are isolated in their own try/except.
    s.record('livemod', 'livekey', status=True, data={'v': 'not-a-number'})
    assert s.get_stats('livemod', 'livekey', 0, time.time() + 1, field='v').get('count')


def test_check_state_key(live_db):
    from lib.services.monitoring.check_state.store import CheckStateStore
    s = CheckStateStore(live_db)
    s.set('livemod', 'livekey', True, message='ok')
    assert ('livemod', 'livekey', '') in s.get_all()
    s.persist_status({'livemod2': {'k2': {'status': False}}})
    assert s.get_all()


def test_audit_user_returns_column_not_current_user(live_db):
    from lib.core.audit.store import AuditStore
    s = AuditStore(live_db)
    s.insert('2026-01-01T00:00:00Z', 'login_ok', 'liveuser', '1.2.3.4', {'x': 1})
    assert any(e['user'] == 'liveuser' for e in s.get_all())    # the column, not CURRENT_USER


def test_groups_reserved_table(live_db):
    from lib.core.groups.store import GroupsStore
    s = GroupsStore(live_db)
    s.save_all({'g1': {'name': 'LiveGrp', 'roles': ['r1'], 'enabled': True}})
    assert s.load().get('g1', {}).get('name') == 'LiveGrp'
    assert s.count() >= 1


def test_events_upsert_same_value(live_db):
    from lib.services.events.store.cursor import CursorStore
    from lib.services.events.store.cooldowns import CooldownsStore
    cur = CursorStore(live_db)
    cur.set_cursor('audit', 5)
    cur.set_cursor('audit', 5)     # same value → UPDATE matches, 0 changed → must NOT re-INSERT
    assert cur.cursor('audit') == 5
    cd = CooldownsStore(live_db)
    cd.set_cooldown('rule-1', 123.0)
    cd.set_cooldown('rule-1', 123.0)
    assert abs(cd.cooldowns().get('rule-1', 0) - 123.0) < 1


def test_schema_rebuild_preserves_data(live_db):
    """A rebuild-type migration (here a nullability change) must keep the data — atomic on
    MySQL (RENAME swap; DDL auto-commits) and transactional on PostgreSQL."""
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    specA = TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT'),
        Column('b', 'INTEGER', nullable=False, default='0')))
    live_db.reconcile_table(specA)
    live_db.execute(f'INSERT INTO {q} (a, b) VALUES (?, ?)', ('keepme', 7)); live_db.commit()
    specB = TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"),   # nullability change → rebuild
        Column('b', 'INTEGER', nullable=False, default='0')))
    live_db.reconcile_table(specB)
    rows = live_db.fetchall(f'SELECT a, b FROM {q}')
    assert rows and rows[0][0] == 'keepme' and int(rows[0][1]) == 7
    assert {c.name: c for c in live_db.describe_table(t)}['a'].nullable is False


def test_introspection_and_incremental_add_column(live_db):
    """Introspection is schema-scoped and an incremental ADD COLUMN (with default) works."""
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    specA = TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''")))
    live_db.reconcile_table(specA)
    assert {'id', 'a'} <= live_db.list_columns(t)
    specB = TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"),
        Column('c', 'TEXT', nullable=False, default="''")))
    live_db.reconcile_table(specB)
    assert 'c' in live_db.list_columns(t)
    assert any(ci.name == 'c' for ci in live_db.describe_table(t))


def test_leader_acquire_renew_steal(live_db):
    """Leader election acquire/renew/steal work on the real engine (PostgreSQL doesn't hit an
    aborted transaction in the common path)."""
    from lib.services.manager.leader import ServiceLeaderStore
    ls = ServiceLeaderStore(live_db)
    assert ls.try_acquire('svc', 'A', ttl=30) is True     # acquire
    assert ls.try_acquire('svc', 'A', ttl=30) is True     # renew
    assert ls.try_acquire('svc', 'B', ttl=30) is False    # B can't steal a valid lease
    live_db.execute('UPDATE service_leader SET expires_at=? WHERE service_key=?', (0, 'svc'))
    live_db.commit()
    assert ls.try_acquire('svc', 'B', ttl=30) is True     # B steals the expired lease
    assert ls.try_acquire('svc', 'A', ttl=30) is False    # A can't re-steal B's valid lease
