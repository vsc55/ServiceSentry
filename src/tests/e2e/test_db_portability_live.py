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
(check_state/history/devices/groups/groups_roles/audit/event_cursor/event_cooldowns). Run them
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

_STORE_TABLES = ('check_state', 'history', 'history_series', 'history_fact',
                 'history_field', 'devices', 'groups',
                 'groups_roles', 'audit',
                 'event_cursor', 'event_cooldowns', 'service_leader',
                 'users', 'users_groups', 'roles', 'config', 'entity_versions',
                 'ss_deftest', '__ssreb_ss_deftest', '__ssbak_ss_deftest',
                 'ss_dc_feature_live', 'ss_dc_type_live', 'ss_dc_platform_live',
                 'ip_bans', 'syslog_drops', 'job_history',
                 'SystemEvents', 'SystemEventsProperties',
                 'ss_t6db_keys', 'ss_t6db_nokey', 'ss_t6db_cpk',
                 '__ssreb_ss_t6db_keys', '__ssbak_ss_t6db_keys')


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

def test_devices_virtual_roundtrip(live_db):
    from lib.core.devices.stores import DevicesStore
    s = DevicesStore(live_db)
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


def test_a_room_piece_with_a_lock_roundtrips(live_db):
    """`dc_feature.lock` is reserved on MySQL/MariaDB (`LOCK TABLES`), and `Rows` wrote every
    column bare: a door with its cylinder could not be listed, created or changed there."""
    import dataclasses
    from lib.core.dcim.store.features import _FEATURE
    from lib.db.rows import Rows
    # Its OWN table, which the fixture drops before and after: `dc_feature` itself may already
    # exist in the scratch database (a panel booted there, an earlier run), and `counts()` is
    # table-wide — rows left by previous runs made it count six lockers instead of one.
    s = Rows(live_db, dataclasses.replace(_FEATURE, name='ss_dc_feature_live'))
    s.bootstrap()
    uid = s.create({'room_uid': 'r1', 'kind': 'door', 'label': 'CPD', 'lock': 'cylinder'},
                   actor='test')
    assert s.get(uid)['lock'] == 'cylinder'
    s.update(uid, {'lock': 'locker'}, actor='test')
    assert [f['lock'] for f in s.list('room_uid = ?', ('r1',))] == ['locker']
    assert s.counts('lock') == {'locker': 1}


def test_the_brands_counts_by_tree_and_by_model_read_on_every_engine(live_db):
    """The brands tab's catalogue reads: a `GROUP BY` over two columns, an `IN` list of model
    uids, chunked, and the platforms per brand. Plain SQL, but the tab draws every brand off them, so they are run on
    the real engines rather than assumed."""
    import dataclasses
    from types import SimpleNamespace
    from lib.core.dcim.catalog import SCHEMA, CatalogStore
    spec = dataclasses.replace(SCHEMA, name='ss_dc_type_live')
    live_db.reconcile_table(spec)
    filas = [('t1', 'b1', 'device-types'), ('t2', 'b1', 'device-types'),
             ('t3', 'b1', 'module-types'), ('t4', 'b2', 'rack-types'), ('t5', '', 'device-types')]
    for uid, marca, arbol in filas:
        live_db.execute('INSERT INTO ss_dc_type_live (uid, manufacturer, model, brand_uid, tree) '
                        'VALUES (?, ?, ?, ?, ?)', (uid, 'M', uid, marca, arbol))
    live_db.commit()
    yo = SimpleNamespace(_db=live_db, _sql_table='ss_dc_type_live')
    assert CatalogStore.brand_tree_counts(yo) == {
        'b1': {'device-types': 2, 'module-types': 1}, 'b2': {'rack-types': 1}}
    assert CatalogStore.brands_of(yo, ['t1', 't4', 't5', 'nope', '']) == {'t1': 'b1',
                                                                         't4': 'b2'}
    # And the platforms, counted per brand the same way: a brand may make only systems.
    from lib.core.dcim.platforms import SCHEMA as PSCHEMA, PlatformStore
    live_db.reconcile_table(dataclasses.replace(PSCHEMA, name='ss_dc_platform_live'))
    for uid, marca in (('p1', 'b3'), ('p2', 'b3'), ('p3', 'b1'), ('p4', '')):
        live_db.execute('INSERT INTO ss_dc_platform_live (uid, name, slug, brand_uid) '
                        'VALUES (?, ?, ?, ?)', (uid, uid, uid, marca))
    live_db.commit()
    plat = SimpleNamespace(_db=live_db, _sql_table='ss_dc_platform_live')
    assert PlatformStore.brand_counts(plat) == {'b3': 2, 'b1': 1}


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
    # And the table still takes rows: the copy carried id 1 across, and on PostgreSQL the new
    # table's sequence did not see it — the next INSERT was handed id 1 again.
    live_db.execute(f'INSERT INTO {q} (a, b) VALUES (?, ?)', ('after', 8)); live_db.commit()
    ids = [int(r[0]) for r in live_db.fetchall(f'SELECT id FROM {q} ORDER BY id')]
    assert len(ids) == 2 and ids[1] > ids[0]


def test_a_rebuild_keeps_the_rows_written_while_it_copied(live_db, monkeypatch):
    """MySQL/MariaDB rebuild by copy + `RENAME TABLE` swap, and a row another session wrote
    to the old table after the copy was in neither — the rebuild lost it. Two late rows are
    planted: one just after the copy commits, one just before the swap (the second can only be
    recovered from the backup table, after the swap). PostgreSQL closes this with a lock (it
    is checked on its SQL in tests/unit/test_tanda5_db.py), so it is not exercised here."""
    if live_db.KIND != 'mysql':
        pytest.skip('the late-row recovery is the MySQL/MariaDB rebuild path')
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('before',)); live_db.commit()

    state = {'copied': False, 'planted': []}
    real_execute, real_commit, real_ddl = live_db.execute, live_db.commit, live_db.execute_ddl

    def _plant(label):
        state['planted'].append(label)
        real_execute(f'INSERT INTO {q} (a) VALUES (?)', (label,))
        real_commit()

    def execute(sql, params=()):
        n = real_execute(sql, params)
        if sql.startswith('INSERT INTO `__ssreb_') and 'NOT EXISTS' not in sql:
            state['copied'] = True
        return n

    def commit():
        real_commit()
        if state['copied'] and not state['planted']:
            _plant('during-copy')

    def execute_ddl(ddl):
        if ddl.startswith('RENAME TABLE'):
            _plant('before-swap')
        return real_ddl(ddl)

    monkeypatch.setattr(live_db, 'execute', execute)
    monkeypatch.setattr(live_db, 'commit', commit)
    monkeypatch.setattr(live_db, 'execute_ddl', execute_ddl)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"))))   # nullability → rebuild
    monkeypatch.undo()

    assert state['planted'] == ['during-copy', 'before-swap']
    got = [r[0] for r in live_db.fetchall(f'SELECT a FROM {q} ORDER BY id')]
    assert got == ['before', 'during-copy', 'before-swap']
    assert not live_db.fetchall(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() "
        "AND table_name = '__ssbak_ss_deftest'")
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('after',)); live_db.commit()
    assert len({r[0] for r in live_db.fetchall(f'SELECT id FROM {q}')}) == 4


def test_two_processes_reconciling_at_once_both_boot(live_db):
    """After an upgrade that adds a column, every process sharing the database reconciles at
    boot. Two reading the same diff both ran `ADD COLUMN` (and its unique index); the second
    failed with «duplicate column» and its boot with it — on every engine. The table is now
    reconciled one process at a time."""
    import threading
    from lib.db.schema import Column, Index, TableSpec
    cfg = {'mysql': _mysql_cfg, 'mariadb': _mariadb_cfg, 'postgresql': _pg_cfg}[live_db._ss_engine]()
    t = 'ss_deftest'
    base = (Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))
    for ronda in range(5):
        live_db.execute_ddl(f'DROP TABLE IF EXISTS {live_db.quote_ident(t)}')
        live_db.reconcile_table(TableSpec(name=t, columns=base))
        nuevo = TableSpec(name=t, columns=base + (
            Column(f'b{ronda}', 'TEXT'), Column(f'c{ronda}', 'TEXT', unique=True)),
            indexes=(Index(f'ix_{t}_b{ronda}', (f'b{ronda}',)),))
        dbs = [get_connector(cfg), get_connector(cfg)]
        barrera, errores = threading.Barrier(2), []

        def boot(db):
            try:
                barrera.wait(10)
                db.reconcile_table(nuevo)
                db.fetchone('SELECT 1')         # and the connection still serves
            except Exception as exc:  # pylint: disable=broad-except
                errores.append(repr(exc))
        hilos = [threading.Thread(target=boot, args=(d,)) for d in dbs]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(60)
        assert not errores, f'round {ronda}: {errores}'
        cols = {c.name for c in live_db.describe_table(t)}
        assert {f'b{ronda}', f'c{ronda}'} <= cols


def _pg_only(live_db):
    if live_db.KIND != 'postgresql':
        pytest.skip('PostgreSQL-specific')


def test_pg_a_rebuild_holds_off_other_writers_until_the_swap(live_db, monkeypatch):
    """P9 on PostgreSQL: from the LOCK on, another session cannot write the table it copies."""
    _pg_only(live_db)
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('before',)); live_db.commit()
    otra = get_connector(_pg_cfg())
    visto = {}
    real = live_db.execute

    def execute(sql, params=()):
        n = real(sql, params)
        if sql.startswith('LOCK TABLE') and 'blocked' not in visto:
            try:
                otra.execute("SET lock_timeout = '300ms'")
                otra.execute(f'INSERT INTO {q} (a) VALUES (?)', ('intruder',))
                otra.commit()
                visto['blocked'] = False
            except Exception:  # pylint: disable=broad-except
                otra.rollback()
                visto['blocked'] = True
        return n

    monkeypatch.setattr(live_db, 'execute', execute)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"))))     # nullability → rebuild
    monkeypatch.undo()
    assert visto.get('blocked') is True, 'another session wrote into the table being copied'
    otra.execute(f'INSERT INTO {q} (a) VALUES (?)', ('after',)); otra.commit()
    assert [r[0] for r in live_db.fetchall(f'SELECT a FROM {q} ORDER BY id')] == ['before', 'after']


def test_pg_an_index_that_cannot_come_back_does_not_undo_the_rebuild(live_db, monkeypatch):
    """On PostgreSQL a failed statement aborts the transaction; the tolerated one is fenced by
    a SAVEPOINT, so the rebuild still lands. A rebuild keeps extra columns, so a real index
    comes back fine; the one that cannot is planted in what the rebuild read beforehand — an
    index over a column that does not exist, which PostgreSQL really refuses."""
    _pg_only(live_db)
    from lib.db.schema import Column, IndexInfo, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('keep',)); live_db.commit()
    real = live_db.list_indexes
    monkeypatch.setattr(live_db, 'list_indexes', lambda table: list(real(table)) + [
        IndexInfo(name='ss_cannot_return', columns=('no_such_column',), unique=False)])
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"))))     # nullability → rebuild
    monkeypatch.undo()
    assert {c.name: c for c in live_db.describe_table(t)}['a'].nullable is False,         'the rebuild was rolled back'
    assert [r[0] for r in live_db.fetchall(f'SELECT a FROM {q}')] == ['keep']


def test_pg_a_restore_does_not_move_the_sequence_back(live_db):
    """P7: ids the events worker has passed must not be handed out again."""
    _pg_only(live_db)
    from lib.core.backup import restore as bk_restore
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True), Column('a', 'TEXT'))))
    for i in range(10):
        live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', (f'r{i}',))
    live_db.commit()
    with live_db.transaction():
        live_db.execute(f'DELETE FROM {q}')
        bk_restore._load_table(                       # pylint: disable=protected-access
            live_db, t, {'columns': ['id', 'a'], 'rows': [[1, 'x'], [2, 'y'], [3, 'z']]})
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('new',)); live_db.commit()
    assert int(live_db.fetchone(f"SELECT id FROM {q} WHERE a = 'new'")[0]) > 10


def test_pg_rebuilds_do_not_pile_up_unique_indexes(live_db):
    """P11: the index behind a UNIQUE constraint was recreated beside the new one each time."""
    _pg_only(live_db)
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'

    def spec(nullable):
        return TableSpec(name=t, columns=(
            Column('id', 'AUTOINCREMENT', primary_key=True),
            Column('code', 'TEXT', unique=True),
            Column('a', 'TEXT', nullable=nullable, default="''")))
    live_db.reconcile_table(spec(True))
    live_db.reconcile_table(spec(False))
    live_db.reconcile_table(spec(True))
    defs = [r[0] for r in live_db.fetchall(
        "SELECT indexdef FROM pg_indexes WHERE tablename = ?", (t,))]
    assert len([d for d in defs if 'UNIQUE' in d.upper() and '(code)' in d]) == 1, defs


def test_pg_an_offset_without_a_limit_pages(live_db):
    """P12: `LIMIT -1` is SQLite's; PostgreSQL refused it."""
    _pg_only(live_db)
    from lib.db.rows import Rows
    from lib.db.schema import Column, TableSpec
    spec = TableSpec(name='ss_deftest', columns=(
        Column('uid', 'TEXT', primary_key=True), Column('a', 'TEXT')))
    live_db.reconcile_table(spec)
    filas = Rows(live_db, spec)
    for i in range(5):
        live_db.execute('INSERT INTO "ss_deftest" (uid, a) VALUES (?, ?)', (f'u{i}', str(i)))
    live_db.commit()
    assert len(filas.list(offset=2)) == 3


def test_pg_a_config_write_moves_its_stamp(live_db):
    """P8 on PostgreSQL: the counter another replica reads moves with every real write."""
    _pg_only(live_db)
    from lib.core.config.store import ConfigStore
    st = ConfigStore(live_db)
    antes = st.stamp()
    st.set_many({'web_admin|x_test': '1'})
    despues = st.stamp()
    assert antes is not None and despues is not None and despues != antes
    st.set_many({'web_admin|x_test': '1'})                  # same value: no real change
    assert st.stamp() == despues


def test_restored_rows_leave_room_for_the_next_insert(live_db):
    """A restore puts rows back WITH their ids; the next plain INSERT must not collide."""
    from lib.core.backup import restore as bk_restore
    from lib.db.schema import Column, TableSpec
    t = 'ss_deftest'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT'))))
    with live_db.transaction():
        rows, _dropped = bk_restore._load_table(       # pylint: disable=protected-access
            live_db, t, {'columns': ['id', 'a'], 'rows': [[1, 'x'], [2, 'y'], [5, 'z']]})
    assert rows == 3
    live_db.execute(f'INSERT INTO {q} (a) VALUES (?)', ('new',)); live_db.commit()
    assert int(live_db.fetchone(f'SELECT MAX(id) FROM {q}')[0]) > 5


def test_text_defaults_reconcile_once_and_then_stay_put(live_db, monkeypatch):
    """A table with TEXT defaults is in sync right after it is created. MySQL 8 reports such a
    default as a `_utf8mb4` introducer plus backslash-escaped quotes; read raw, every boot saw
    a drift and rebuilt the table."""
    from lib.db.schema import Column, TableSpec, diff_table
    t = 'ss_deftest'
    spec = TableSpec(name=t, columns=(
        Column('id', 'AUTOINCREMENT', primary_key=True),
        Column('a', 'TEXT', nullable=False, default="''"),
        Column('b', 'TEXT', nullable=False, default="'{}'"),
        Column('c', 'TEXT', nullable=False, default="'local'"),
        Column('n', 'INTEGER', nullable=False, default='0')))
    live_db.reconcile_table(spec)
    diff = diff_table(spec, live_db.describe_table(t), live_db.list_indexes(t))
    assert diff.is_empty, f'drift reported right after creation: {diff}'
    rebuilds = []
    monkeypatch.setattr(live_db, '_apply_rebuild', lambda *a, **k: rebuilds.append(a))
    live_db.reconcile_table(spec)
    assert rebuilds == []


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
                    # KEYWORD_ONLY cuenta igual que posicional: un parámetro obligatorio es
                    # obligatorio se pase como se pase. Sin él, `ApiTokenStore.create(*,
                    # user_uid, name, token_id, ...)` pasaba el filtro —no tiene ni uno
                    # posicional— y se llamaba sin argumentos, que es un TypeError contado como
                    # «lectura que falla en el motor vivo». El barrido es de lecturas SIN
                    # parámetros; ésa tiene ocho.
                    if any(p.default is inspect.Parameter.empty
                           and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD,
                                          p.KEYWORD_ONLY)
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


# ── trims that ran inside the write's own transaction ─────────────────────────
#
# `DELETE … WHERE k IN (SELECT … LIMIT n)` (MySQL 1093 / MariaDB 1235) and `LIMIT -1 OFFSET n`
# (SQLite only) both used to roll back the write beside them. The caps are lowered so the trim
# runs on a handful of rows instead of thousands.

def test_the_ban_cap_trims_without_losing_the_new_ban(live_db, monkeypatch):
    from lib.services.ipban.store import bans as bans_mod
    monkeypatch.setattr(bans_mod, '_MAX_ROWS', 3)
    st = bans_mod.BansStore(live_db)
    for i in range(5):
        st.upsert(f'10.0.0.{i}', {'reason': 'r', 'category': 'auth', 'level': 1,
                                  'offenses': 1, 'banned_at': 1000.0 + i, 'until': None,
                                  'first_seen': 1000.0 + i, 'by': 'system'})
    assert sorted(r['ip'] for r in st.query()) == ['10.0.0.2', '10.0.0.3', '10.0.0.4']


def test_the_drop_cap_trims_without_losing_the_new_source(live_db, monkeypatch):
    from lib.services.syslog.store import drops as drops_mod
    monkeypatch.setattr(drops_mod, '_MAX_ROWS', 3)
    st = drops_mod.SyslogDropsStore(live_db)
    for i in range(5):
        st.record(f'10.0.0.{i}', 'udp', 1, 1000.0 + i)
    assert sorted(r['source'] for r in st.query()) == ['10.0.0.2', '10.0.0.3', '10.0.0.4']


def test_the_job_history_ceiling_and_age_limit_both_apply(live_db):
    from lib.core.jobs.history import JobHistoryStore
    st = JobHistoryStore(live_db)
    now = time.time()

    def _job(jid, ended):
        return {'id': jid, 'kind': 'collect', 'source': 'infra', 'label': jid,
                'state': 'done', 'started': ended - 1, 'ended': ended, 'done': 1,
                'total': 1, 'error': ''}
    st.record(_job('old', now - 40 * 86400))
    for i in range(6):
        st.record(_job(f'x{i}', now - 100 + i))
    assert st.prune(keep=4, days=30) == 3
    assert [r['job_id'] for r in st.list()] == ['x5', 'x4', 'x3', 'x2']


def test_the_audit_cap_trims_to_the_cap_even_after_it_is_lowered(live_db):
    """`DELETE … WHERE id = (SELECT MIN(id) FROM audit)` is MySQL 8 error 1093, and it took one
    row per insert. Now: the cutoff id is read first, then one plain `DELETE … WHERE id < ?`."""
    from lib.core.audit.store import AuditStore
    s = AuditStore(live_db)
    for i in range(8):
        s.insert(f'2026-01-01T00:00:0{i}Z', f'e{i}', 'u', 'ip', '')
    s.insert('2026-01-01T00:00:09Z', 'e8', 'u', 'ip', '', max_entries=3)
    assert [e['event'] for e in s.get_all()] == ['e8', 'e7', 'e6']


# ── rsyslog's own table, created by rsyslog's own script ─────────────────────
# plugins/ommysql/createDB.sql and plugins/ompgsql/createDB.sql, minus the CREATE DATABASE.
_RSYSLOG_COLS = """
        CustomerID bigint,
        ReceivedAt {dt} NULL,
        DeviceReportedTime {dt} NULL,
        Facility smallint NULL,
        Priority smallint NULL,
        FromHost varchar(63) NULL,
        Message text,
        NTSeverity int NULL,
        Importance int NULL,
        EventSource varchar(60),
        EventUser varchar(60) NULL,
        EventCategory int NULL,
        EventID int NULL,
        EventBinaryData text NULL,
        MaxAvailable int NULL,
        CurrUsage int NULL,
        MinUsage int NULL,
        MaxUsage int NULL,
        InfoUnitID int NULL ,
        SysLogTag varchar(60),
        EventLogType varchar(60),
        GenericFileName VarChar(60),
        SystemID int NULL"""


def _rsyslog_create(db):
    pg = db.KIND == 'postgresql'
    key = 'ID serial not null primary key' if pg else \
        'ID int unsigned not null auto_increment primary key'
    dt = 'timestamp without time zone' if pg else 'datetime'
    db.execute_ddl(f'CREATE TABLE SystemEvents ( {key},{_RSYSLOG_COLS.format(dt=dt)} )')
    pkey = key
    db.execute_ddl(f'CREATE TABLE SystemEventsProperties ( {pkey}, SystemEventID int NULL , '
                   'ParamName varchar(255) NULL , ParamValue text NULL )')


def test_rsyslogs_table_is_adopted_and_both_sides_read_each_other(live_db):
    """rsyslog created the table and wrote to it with its stock template, on the real engine:
    the store must adopt it without a rebuild and read those rows; what the store writes must
    be what rsyslog's readers find. PostgreSQL folds rsyslog's unquoted names to lower case,
    MySQL needs a VARCHAR for every indexed column the store adds — both only show here."""
    from datetime import datetime, timezone
    from lib.services.syslog.store import SyslogStore
    from lib.services.syslog.store import messages as msgs

    _rsyslog_create(live_db)
    now = int(time.time())
    utc = datetime.fromtimestamp(now, timezone.utc)
    # The stock template's dates: `date-mysql` is YYYYMMDDHHMMSS, `date-pgsql` ISO.
    when = utc.strftime('%Y-%m-%d %H:%M:%S' if live_db.KIND == 'postgresql' else '%Y%m%d%H%M%S')
    live_db.execute('INSERT INTO SystemEvents (Message, Facility, FromHost, Priority, '
                    'DeviceReportedTime, ReceivedAt, InfoUnitID, SysLogTag) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    ('Accepted password', 4, 'web01', 6, when, when, 1, 'sshd[812]:'))
    live_db.commit()

    diff = live_db.reconcile_table(msgs._SCHEMA)
    assert not diff.needs_rebuild, diff
    store = SyslogStore(live_db)
    assert live_db.reconcile_table(msgs._SCHEMA).is_empty     # and a second boot: nothing

    row = store.query()[0]
    assert (row['hostname'], row['app'], row['procid'], row['severity'], row['ts']) == \
        ('web01', 'sshd', '812', 6, now)

    store.add({'ts': now + 1, 'source': '10.0.0.9', 'hostname': 'fw1', 'app': 'kernel',
               'procid': '', 'severity': 3, 'facility': 0, 'msgid': '', 'message': 'ours',
               'raw': '<3>ours', 'timestamp': ''})
    assert [r['message'] for r in store.query()] == ['ours', 'Accepted password']
    assert [r['message'] for r in store.query({'app': 'kernel'})] == ['ours']
    assert [r['message'] for r in store.query({'since': now + 1})] == ['ours']
    got = live_db.fetchone('SELECT Message, Priority, FromHost, SysLogTag, InfoUnitID '
                           'FROM SystemEvents WHERE FromHostIP = ?', ('10.0.0.9',))
    assert tuple(got) == ('ours', 3, 'fw1', 'kernel:', 1)
    st = store.stats()
    assert st['total'] == 2 and {s['value'] for s in st['by_severity']} == {3, 6}


def test_rsyslogs_database_is_read_without_being_touched(live_db):
    """`syslog_db|mode = external` on the real engine: rsyslog's table as its script made it,
    read with the columns it has — and after that, still exactly as its script made it."""
    from lib.services.syslog.store import SyslogStore

    _rsyslog_create(live_db)
    when = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    live_db.execute('INSERT INTO SystemEvents (Message, Facility, FromHost, Priority, '
                    'DeviceReportedTime, ReceivedAt, InfoUnitID, SysLogTag) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    ('read only', 4, 'web01', 6, when, when, 1, 'sshd[812]:'))
    live_db.commit()
    before = [c.name for c in live_db.describe_table('SystemEvents')]

    store = SyslogStore(live_db, read_only=True)
    assert [r['app'] for r in store.query()] == ['sshd']
    assert store.query({'source': '10.0.0.1'}) == []
    assert len(store.query(sort='source')) == 1          # PostgreSQL refuses ORDER BY NULL
    st = store.stats()
    assert st['total'] == 1 and st['by_device'][0]['value'] == 'web01'
    assert [c.name for c in live_db.describe_table('SystemEvents')] == before
    assert live_db.list_indexes('SystemEvents') == []


def test_an_external_source_never_blocks_its_owners_ddl(live_db):
    """Reported while trying it on MariaDB: after the panel READ an external source, the
    owner's `DROP TABLE` hung. The connector ran without autocommit, so every SELECT left a
    transaction open, and on MySQL that holds a metadata lock on the table — the DBA adding an
    index waited on the panel's idle connection for as long as it stayed open. External
    sources now read in autocommit."""
    import threading
    from lib.services.syslog import sources as srcmod

    _rsyslog_create(live_db)
    cfg = dict(live_db._config)
    store = srcmod.open_source({'name': 'live', 'time_zone': 'UTC', 'data': cfg})
    assert store.count() == 0                         # the read that used to leave the lock
    done = []

    def ddl():
        live_db.execute_ddl('CREATE INDEX idx_live_dba ON SystemEvents (ReceivedAt)')
        done.append(True)

    worker = threading.Thread(target=ddl, daemon=True)
    worker.start()
    worker.join(15)
    store._db.close()
    assert done, "the owner's CREATE INDEX waited on the panel's idle read"


# ── second audit of 2026-10-12: DB-1, DB-2, DB-6, DB-7 on the real engines ──

def test_a_rebuild_carries_an_undeclared_varchar_column_whole(live_db):
    """DB-1: a column the spec no longer declares is carried across a rebuild. MySQL/MariaDB
    recreated it from `data_type` — `varchar` with no length, error 1064 — so the rebuild
    failed on every boot; its default and NOT NULL must survive too."""
    from lib.db.schema import Column, TableSpec
    t = 'ss_t6db_keys'
    q = live_db.quote_ident(t)
    live_db.reconcile_table(TableSpec(name=t, columns=(
        Column('uid', 'TEXT', primary_key=True), Column('n', 'INTEGER'))))
    live_db.execute_ddl(f"ALTER TABLE {q} ADD COLUMN {live_db.quote_ident('tag')} "
                        "VARCHAR(40) NOT NULL DEFAULT 'x'")
    live_db.execute(f"INSERT INTO {q} (uid, n, tag) VALUES ('a', 1, 't')")
    live_db.commit()
    live_db.reconcile_table(TableSpec(name=t, columns=(        # n: INTEGER -> REAL, rebuild
        Column('uid', 'TEXT', primary_key=True), Column('n', 'REAL'))))
    cols = {c.name: c for c in live_db.describe_table(t)}
    assert 'tag' in cols and cols['tag'].nullable is False
    assert live_db.fetchone(f'SELECT tag FROM {q}')[0] == 't'
    live_db.execute(f"INSERT INTO {q} (uid, n) VALUES ('b', 2)")
    live_db.commit()
    assert live_db.fetchone(f"SELECT tag FROM {q} WHERE uid = 'b'")[0] == 'x'


def _mysql_only(live_db):
    if live_db.KIND != 'mysql':
        pytest.skip('MySQL/MariaDB-specific')


def test_keys_that_differ_only_in_case_or_accent_stay_two(live_db):
    """DB-2: the default collation is case- and accent-insensitive on MySQL/MariaDB, so a
    unique key merged `Rx` and `rx` (the second history field's sample lost every cycle)."""
    from lib.core.history.store import HistoryStore
    h = HistoryStore(live_db)
    h.record('snmp', 'host1/Gi0/1', True, {'Rx': 1, 'rx': 2, 'cafe': 3, 'café': 4})
    h.record('web', 'Intranet', True, {'v': 1})
    h.record('web', 'intranet', False, {'v': 2})
    got = h.query('snmp', 'host1/Gi0/1', 0, time.time() + 5)
    assert got and got[-1]['data'] == {'Rx': 1, 'rx': 2, 'cafe': 3, 'café': 4}
    assert [p['data'] for p in h.query('web', 'Intranet', 0, time.time() + 5)] == [{'v': 1}]
    assert [p['data'] for p in h.query('web', 'intranet', 0, time.time() + 5)] == [{'v': 2}]


def test_an_existing_case_insensitive_unique_key_is_migrated(live_db):
    """DB-2 on a table made before the fix: its unique TEXT key is converted in place to
    `utf8mb4_bin` (length kept), and only then does `Rx` beside `rx` fit."""
    _mysql_only(live_db)
    from lib.db.schema import Column, Index, TableSpec
    t = 'ss_t6db_keys'
    live_db.execute_ddl(f'CREATE TABLE {t} (id INT AUTO_INCREMENT PRIMARY KEY, '
                        'name VARCHAR(255) CHARACTER SET utf8mb4 '
                        'COLLATE utf8mb4_general_ci NOT NULL)')
    live_db.execute_ddl(f'CREATE UNIQUE INDEX ix_t6db_name ON {t} (name)')
    live_db.execute(f"INSERT INTO {t} (name) VALUES ('Rx')")
    live_db.commit()
    spec = TableSpec(name=t, columns=(Column('id', 'AUTOINCREMENT', primary_key=True),
                                      Column('name', 'TEXT', nullable=False)),
                     indexes=(Index('ix_t6db_name', ('name',), unique=True),))
    live_db.reconcile_table(spec)
    col = {c.name: c for c in live_db.describe_table(t)}['name']
    assert col.collation == 'utf8mb4_bin' and col.definition.startswith('varchar(255)')
    live_db.execute(f"INSERT INTO {t} (name) VALUES ('rx')")
    live_db.commit()
    assert live_db.fetchone(f'SELECT COUNT(*) FROM {t}')[0] == 2
    assert live_db.reconcile_table(spec).is_empty           # and the next boot: nothing


def test_a_swallowed_error_does_not_leave_a_lock_behind(live_db):
    """DB-6: MySQL keeps the transaction open after a failed statement. A caller that
    swallowed the error and only read afterwards held the table's metadata lock for good,
    and the owner's next ALTER waited behind an idle connection (1205)."""
    _mysql_only(live_db)
    import pymysql
    t = 'ss_t6db_keys'
    live_db.execute_ddl(f'CREATE TABLE {t} (k VARCHAR(10) PRIMARY KEY, v INT)')
    live_db.execute(f"INSERT INTO {t} VALUES ('a', 1)")
    live_db.commit()
    with pytest.raises(pymysql.err.IntegrityError):
        live_db.execute(f"INSERT INTO {t} VALUES ('a', 2)")     # the lost race, swallowed
    for _ in range(3):
        live_db.fetchall(f'SELECT v FROM {t}')                  # and only reads after it
    cfg = live_db._config
    other = pymysql.connect(host=cfg['host'], port=int(cfg['port']), user=cfg['user'],
                            password=cfg['password'], db=cfg['name'])
    try:
        with other.cursor() as cur:
            cur.execute('SET SESSION lock_wait_timeout = 3')
            cur.execute(f'ALTER TABLE {t} ADD COLUMN w INT')    # raises 1205 when blocked
    finally:
        other.close()


def test_a_copy_pages_by_key_and_streams_what_has_none(live_db):
    """DB-7 on the real engines: keyset pages over a single and a composite key (row-value
    comparison), the keyless table through the engine's streaming cursor (MySQL's SSCursor,
    PostgreSQL's named cursor), and the batches restored back."""
    import io
    import zipfile
    from lib.core.backup import archive as bk_archive
    from lib.core.backup import create as bk_create
    from lib.core.backup import restore as bk_restore
    from lib.db.schema import Column, TableSpec
    live_db.reconcile_table(TableSpec('ss_t6db_keys', (
        Column('uid', 'TEXT', primary_key=True), Column('v', 'TEXT'))))
    live_db.reconcile_table(TableSpec('ss_t6db_cpk', (
        Column('a', 'INTEGER'), Column('b', 'TEXT'), Column('v', 'INTEGER')),
        composite_pk=('a', 'b')))
    live_db.reconcile_table(TableSpec('ss_t6db_nokey', (
        Column('n', 'INTEGER'), Column('v', 'TEXT'))))
    q = live_db.quote_ident
    live_db.executemany(f"INSERT INTO {q('ss_t6db_keys')} (uid, v) VALUES (?, ?)",
                        [(f'u{i:03d}', f'line\n{i}') for i in range(23)])
    live_db.executemany(f"INSERT INTO {q('ss_t6db_cpk')} (a, b, v) VALUES (?, ?, ?)",
                        [(a, f'b{b}', a * 10 + b) for a in range(4) for b in range(5)])
    live_db.executemany(f"INSERT INTO {q('ss_t6db_nokey')} (n, v) VALUES (?, ?)",
                        [(i % 3, f'x{i}') for i in range(17)])
    live_db.commit()
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, 'w') as zf:
        for t in ('ss_t6db_keys', 'ss_t6db_cpk', 'ss_t6db_nokey'):
            info = live_db.describe_table(t)
            cols = [c.name for c in info]
            pk = [c.name for c in sorted((c for c in info if c.pk), key=lambda c: c.pk)]
            sizes = []

            def batches(cols=cols, pk=pk, t=t, sizes=sizes):
                for b in bk_create._table_batches(live_db, t, cols, pk, size=5):
                    sizes.append(len(b))
                    yield [[bk_archive.clean_cell(v, True) for v in r] for r in b]
            counts[t], _sha = bk_archive.write_table_member(zf, f'db/{t}.json', cols,
                                                            batches())
            assert max(sizes) <= 5 and sum(sizes) == counts[t], (t, sizes)
    assert counts == {'ss_t6db_keys': 23, 'ss_t6db_cpk': 20, 'ss_t6db_nokey': 17}
    before = {t: sorted(map(tuple, live_db.fetchall(f'SELECT * FROM {q(t)}')))
              for t in counts}
    with zipfile.ZipFile(buf) as zf, live_db.transaction():
        for t in counts:
            cols, batches = bk_archive.iter_table_member(zf, f'db/{t}.json', size=4)
            assert bk_restore._load_table(live_db, t, cols, batches) == (counts[t], [])
    after = {t: sorted(map(tuple, live_db.fetchall(f'SELECT * FROM {q(t)}')))
             for t in counts}
    assert after == before
