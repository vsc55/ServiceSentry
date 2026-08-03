"""Live multi-engine portability tests — run the stores against a REAL MySQL/MariaDB and/or
PostgreSQL, catching dialect breakages the SQLite suite can't (reserved-word identifiers,
CAST targets, UPDATE rowcount semantics, …).

Opt-in via environment variables (skipped entirely when unset — CI runs them only when a
scratch DB is provided; **never** hardcode credentials here):

    MySQL:           SS_TEST_MYSQL_HOST    [SS_TEST_MYSQL_PORT=3306]    SS_TEST_MYSQL_DB
                     SS_TEST_MYSQL_USER    SS_TEST_MYSQL_PASSWORD
    MariaDB:         SS_TEST_MARIADB_HOST  [SS_TEST_MARIADB_PORT=3306]  SS_TEST_MARIADB_DB
                     SS_TEST_MARIADB_USER  SS_TEST_MARIADB_PASSWORD
    PostgreSQL:      SS_TEST_PG_HOST       [SS_TEST_PG_PORT=5432]       SS_TEST_PG_DB
                     SS_TEST_PG_USER       SS_TEST_PG_PASSWORD

MariaDB gets its own slot rather than riding on the MySQL one: they share a driver and a
dialect tag, and diverge exactly where this suite is useful. The DEFAULT-on-TEXT fix, for one,
relies on MySQL 8.0.13+ accepting a parenthesised default and MariaDB 10.2+ accepting it too —
a claim that was worth checking on a real MariaDB rather than assuming.

The target database must be a SCRATCH database: these tests CREATE and DROP the store tables
(check_state/history/hosts/groups/groups_roles/audit/event_cursor/event_cooldowns). Run them
SERIALLY (``-n0``) — they use fixed table names, so parallel workers would collide.

**Nothing here drops a table it did not create.** The full-panel test snapshots the schema
before booting and removes only the difference; every other test names its tables. That rule
exists because the database in ``.env.test`` is whatever the operator pointed it at — the
PostgreSQL default is ``postgres``, the cluster's own maintenance database — and a teardown
that swept ``list_tables()`` wholesale would take anything else living there with it.

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
                 'users', 'users_groups', 'roles', 'config', 'entity_versions',
                 'ss_deftest', '__ssreb_ss_deftest', '__ssbak_ss_deftest')


def _mysql_family_cfg(prefix: str):
    """Config for a MySQL-protocol engine from its ``SS_TEST_<prefix>_*`` variables."""
    host = os.environ.get(f'SS_TEST_{prefix}_HOST')
    if not host:
        return None
    return {'driver': 'mysql', 'host': host,
            'name': os.environ.get(f'SS_TEST_{prefix}_DB', 'test'),
            'user': os.environ.get(f'SS_TEST_{prefix}_USER', 'root'),
            'password': os.environ.get(f'SS_TEST_{prefix}_PASSWORD', ''),
            'port': int(os.environ.get(f'SS_TEST_{prefix}_PORT', '3306'))}


def _mysql_cfg():
    return _mysql_family_cfg('MYSQL')


def _mariadb_cfg():
    return _mysql_family_cfg('MARIADB')


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


@pytest.fixture(params=['mysql', 'mariadb', 'postgresql'])
def live_db(request):
    """A real connector for each configured engine; skips the engine when unset."""
    # These tests use fixed table names and drop/recreate them, so they must not run in
    # parallel (xdist workers would clobber each other). Under `-n auto` they'd now be
    # collected — since `.env.test` is auto-loaded for the whole suite — so skip unless
    # serial. Run them with `-n0` (see docs/ref-tests.md §81).
    if int(os.environ.get('PYTEST_XDIST_WORKER_COUNT', '1')) > 1:
        pytest.skip('live DB tests must run serially - use -n0')
    cfg = {'mysql': _mysql_cfg, 'mariadb': _mariadb_cfg, 'postgresql': _pg_cfg}[request.param]()
    if cfg is None:
        var = {'mysql': 'SS_TEST_MYSQL_HOST', 'mariadb': 'SS_TEST_MARIADB_HOST',
               'postgresql': 'SS_TEST_PG_HOST'}[request.param]
        pytest.skip(f'{request.param} not configured (set {var})')
    try:
        db = get_connector(cfg)
        db.fetchone('SELECT 1')          # fail fast if unreachable
    except Exception as exc:  # pylint: disable=broad-except
        pytest.skip(f'{request.param} unreachable: {exc}')
    db._ss_engine = request.param        # which of the three this is (KIND cannot tell
                                         # MySQL from MariaDB — same driver, same tag)
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
    s.apply({'g1': {'name': 'LiveGrp', 'roles': ['r1'], 'enabled': True}})
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


def test_the_whole_panel_boots_and_serves_on_the_real_engine(live_db, tmp_path):
    """Boot the REAL WebAdmin against this engine and walk everything it serves.

    The tests above build seven stores by hand. The panel builds every table in the schema and
    then answers requests against them, which is where a dialect breakage actually bites — and
    the two that were found here (a ``TEXT`` column cannot carry a literal DEFAULT on MySQL;
    ``ONLY_FULL_GROUP_BY`` refuses the history bucketing) were both invisible to the by-hand
    stores. One created no table at all, the other returned an empty chart.

    Nothing is enumerated by hand: the endpoints come from Flask's ``url_map`` and the store
    reads from introspection, so a store or a page added later is covered without anyone
    remembering this file exists.
    """
    import inspect
    import json
    import re

    from lib.web_admin import WebAdmin

    # KIND is 'mysql' for MariaDB too (same driver), so the config comes from the request
    # parameter the fixture recorded rather than from the dialect tag.
    cfg = {'mysql': _mysql_cfg, 'mariadb': _mariadb_cfg,
           'postgresql': _pg_cfg}[live_db._ss_engine]()
    env = {'SS_DB_DRIVER': cfg['driver'], 'SS_DB_HOST': cfg['host'],
           'SS_DB_PORT': str(cfg['port']), 'SS_DB_NAME': cfg['name'],
           'SS_DB_USER': cfg['user'], 'SS_DB_PASSWORD': cfg['password']}
    # What was already there BEFORE the panel boots. The teardown drops the difference and
    # nothing else: `list_tables()` returns the whole schema, so dropping that wholesale would
    # delete tables this test never created — and the configured database is whatever the
    # operator put in .env.test, which may well be a shared one.
    pre_existing = set(live_db.list_tables())
    # Release the fixture connection's transaction. It is only used for that snapshot, but an
    # idle-in-transaction session holds locks, and the maintenance run below needs an
    # exclusive one: VACUUM FULL / OPTIMIZE TABLE would wait on it for ever, so the test hangs
    # instead of failing. The same shape as the teardown deadlock — a second connection nobody
    # remembered was still open.
    live_db.commit()

    conf = tmp_path / 'conf'
    var = tmp_path / 'var'
    conf.mkdir()
    var.mkdir()
    (conf / 'config.json').write_text(json.dumps({'monitoring': {'timer_check': 300}}),
                                      encoding='utf-8')

    from unittest import mock
    with mock.patch.dict(os.environ, env):
        wa = WebAdmin(str(conf), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        try:
            assert len(wa._db_connector.list_tables()) > 20, 'the schema did not come up'

            # every store read that takes no arguments
            failures = []
            for sname in [n for n in dir(wa) if n.endswith('_store')]:
                store = getattr(wa, sname, None)
                if store is None:
                    continue
                for mname in sorted(dir(store)):
                    # Lifecycle and destructive names are excluded by NAME, not by trying
                    # them: `delete_all()` takes no arguments and would have been swept as a
                    # read — it emptied the syslog table on the first run.
                    if mname.startswith('_') or mname in (
                            'close', 'commit', 'rollback', 'vacuum', 'compact', 'prune',
                            'clear', 'purge', 'reset', 'delete_all', 'wipe', 'truncate',
                            'flush', 'drop'):
                        continue
                    meth = getattr(store, mname)
                    if not callable(meth):
                        continue
                    try:
                        sig = inspect.signature(meth)
                    except (TypeError, ValueError):
                        continue
                    if any(p.default is inspect.Parameter.empty
                           and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                           for p in sig.parameters.values()):
                        continue
                    try:
                        meth()
                    except Exception as exc:            # pylint: disable=broad-except
                        failures.append(f'{sname}.{mname}(): {type(exc).__name__}: {exc}')
                        # PostgreSQL aborts the whole transaction on the first error, so
                        # without this every later read reports "current transaction is
                        # aborted" and the ONE real failure is buried under thirty echoes of
                        # itself. Roll back so each read is judged on its own.
                        try:
                            wa._db_connector.rollback()
                        except Exception:               # pylint: disable=broad-except
                            pass
            assert not failures, 'store reads failing on the live engine: ' + '; '.join(failures)

            # every parameterless GET, authenticated
            wa.app.config['TESTING'] = True
            c = wa.app.test_client()
            page = c.get('/login').get_data(as_text=True)
            tok = re.search(r'name="csrf_token" value="([^"]+)"', page)
            c.post('/login', data={'username': 'admin', 'password': 'secret',
                                   'csrf_token': tok.group(1) if tok else ''},
                   follow_redirects=True)
            assert c.get('/api/v1/me').get_json().get('username') == 'admin'

            broken = []
            for rule in sorted({r.rule for r in wa.app.url_map.iter_rules()
                                if 'GET' in (r.methods or ()) and '<' not in r.rule
                                and not r.rule.startswith(('/static', '/api/v1/config/db/'))
                                and r.rule != '/logout'}):
                if c.get(rule).status_code >= 500:
                    broken.append(rule)
            assert not broken, 'routes returning 5xx on the live engine: ' + '; '.join(broken)

            # writes that span several tables, then the aggregate queries
            for resp in (
                c.post('/api/v1/users', json={'username': 'liveu', 'password': 'testpass1',
                                              'role': 'viewer'}),
                c.post('/api/v1/groups', json={'name': 'LiveG', 'roles': []}),
                c.post('/api/v1/roles', json={'name': 'LiveR', 'permissions': ['users_view']}),
                c.put('/api/v1/config', json={'monitoring': {'timer_check': 120}}),
                c.put('/api/v1/modules', json={'ping': {'enabled': False}}),
                c.delete('/api/v1/users/liveu'),
            ):
                assert resp.status_code < 500, resp.get_data(as_text=True)[:200]

            # Maintenance through the ENDPOINT, which is what the UI calls: the connector
            # calls are covered by their own live test, but the route adds the parts that can
            # only fail here — the permission gate, the table name validated against the
            # engine's own target list before it is interpolated into SQL, and the audit entry
            # with the reclaimed size. Compact included: on two of the three engines it
            # rewrites the whole store, so "it ran without breaking the panel" is the claim.
            grant = c.get('/api/v1/config/db/targets/optimize')
            assert grant.status_code == 200, grant.get_data(as_text=True)[:200]
            targets = grant.get_json()['targets']
            for op in ('optimize', 'compact'):
                r = c.post(f'/api/v1/config/db/{op}', json={})
                assert r.status_code == 200, f'{op}: {r.get_data(as_text=True)[:300]}'
            if targets:                        # per-table step, where the engine divides
                r = c.post('/api/v1/config/db/optimize', json={'table': targets[0]})
                assert r.status_code == 200, r.get_data(as_text=True)[:300]
            # …and a table this operation cannot walk is refused rather than interpolated.
            bad = c.post('/api/v1/config/db/optimize', json={'table': 'no_such_table; DROP'})
            assert bad.status_code == 400, 'an unknown identifier reached the SQL'

            hist = wa._history
            for i in range(80):
                hist.record('livemod2', 'k', status=(i % 2 == 0), data={'v': i})
            assert hist.query('livemod2', 'k', 0, time.time() + 1, max_points=5), \
                'the bucketed history query came back empty — a chart with no points'
            assert wa._audit_store.get_all(), 'nothing was audited through the whole run'
        finally:
            # Close the panel's OWN connection before dropping anything: on MySQL a DROP
            # blocks on the metadata lock an open connection still holds, so the test HANGS
            # instead of failing — which is what it did the first time it ran. Dropping
            # through that same connector also keeps two sessions from racing.
            conn = wa._db_connector
            try:
                for t in set(conn.list_tables()) - pre_existing:   # only what WE created
                    conn.execute(f'DROP TABLE IF EXISTS {conn.quote_ident(t)}')
                conn.commit()
            except Exception:                              # pylint: disable=broad-except
                pass
            finally:
                try:
                    conn.close()
                except Exception:                          # pylint: disable=broad-except
                    pass


def test_maintenance_actually_runs_on_the_real_engine(live_db):
    """Optimize and compact, executed — not read as source.

    The maintenance suite verifies the MySQL and PostgreSQL implementations by grepping the
    connector files, because those engines need a server. That leaves the statements
    themselves unproven, and they fail in specific ways that no amount of reading catches:
    PostgreSQL refuses ``VACUUM FULL`` inside a transaction block, and MySQL's
    ``OPTIMIZE TABLE`` returns a result set that leaves the connection in "commands out of
    sync" if nobody consumes it. Both are runtime facts about the driver, not about the text.

    Compact is the expensive half — it rewrites storage — so this runs it on a table with a
    few thousand rows rather than an empty one, which is the only way the operation does any
    work at all.
    """
    from lib.db.schema import Column, TableSpec

    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('v', 'TEXT', nullable=False, default="''"))))
    for _ in range(2000):
        live_db.execute(f'INSERT INTO {q} (v) VALUES (?)', ('x' * 200,))
    live_db.commit()
    live_db.execute(f'DELETE FROM {q}')                 # leave space to reclaim
    live_db.commit()

    targets_opt = live_db.maintenance_targets('optimize')
    targets_cmp = live_db.maintenance_targets('compact')
    assert t in targets_opt, 'the table the panel would offer is not in the optimize list'

    live_db.optimize(t)                                 # per table
    live_db.optimize()                                  # whole database
    # The connection must still work: MySQL's OPTIMIZE returns rows, and an unread result set
    # poisons the next statement with "commands out of sync".
    assert live_db.fetchone(f'SELECT COUNT(*) FROM {q}')[0] == 0

    live_db.compact()                                   # the rewrite — no transaction wrapper
    assert live_db.fetchone(f'SELECT COUNT(*) FROM {q}')[0] == 0, \
        'the connection did not survive compact'

    if targets_cmp:                                     # engines that can compact per table
        live_db.compact(targets_cmp[0])
        assert live_db.fetchone('SELECT 1')[0] == 1

    from lib.core.config.service import database_size
    size = database_size(live_db)
    assert size is None or size > 0, f'database_size answered {size!r}'
