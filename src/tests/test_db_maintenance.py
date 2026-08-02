#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optimize and compact: the two halves of database maintenance, and why they stay apart.

Deleting a year of history frees nothing an operator can see — the rows go, the file does
not shrink, and the disk graph keeps climbing. Reclaiming that space is a database operation
the panel never offered, so the only way to do it was a shell on the host.

The two are separate actions because they cost wildly different things. ``optimize`` reads
the data and updates the statistics the query planner uses to pick an index: cheap, safe, and
worth running often. ``compact`` rewrites storage to hand free space back to the filesystem,
and holds the database while it does — ``VACUUM FULL`` locks every table on PostgreSQL,
``OPTIMIZE TABLE`` rebuilds on InnoDB. Offering only the combined operation would mean the
safe one could never be run on its own, which is the one you actually want on a schedule.

The engines disagree about all of it, which is the point of testing through the connector:
SQLite has one rewrite that both names mean, PostgreSQL has two genuinely different
statements, and MySQL has no database-wide form at all and must name each table.
"""

import io
import os

import pytest

from lib.core.config.service import database_size
from lib.db.base import BaseConnector
from lib.db.sqlite import SQLiteConnector

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def db(tmp_path):
    """A SQLite database with real rows in it — the only engine testable without a server."""
    conn = SQLiteConnector(str(tmp_path / 'maint.db'))
    conn.execute_ddl('CREATE TABLE demo (id INTEGER PRIMARY KEY, v TEXT)')
    for _ in range(2000):
        conn.execute('INSERT INTO demo (v) VALUES (?)', ('x' * 300,))
    conn.commit()
    conn.checkpoint()
    yield conn
    conn.close()


class TestCompactReclaimsSpace:

    def test_deleting_rows_alone_frees_nothing(self, db):
        """The premise. Without this the next test proves nothing: if a delete already shrank
        the file, compacting would look like it worked while doing nothing at all."""
        before = database_size(db)
        db.execute('DELETE FROM demo')
        db.commit()
        db.checkpoint()
        assert database_size(db) >= before * 0.9, \
            'the delete already reclaimed the space — this fixture no longer tests anything'

    def test_compact_returns_it(self, db):
        db.execute('DELETE FROM demo')
        db.commit()
        db.checkpoint()
        before = database_size(db)
        db.compact()
        after = database_size(db)
        assert after < before, f'compact reclaimed nothing: {before} -> {after}'

    def test_the_data_survives_it(self, db):
        """A rewrite that loses rows is not a compaction."""
        db.execute("DELETE FROM demo WHERE id > 100")
        db.commit()
        db.compact()
        assert db.fetchone('SELECT COUNT(*) FROM demo')[0] == 100

    def test_the_connection_still_works_afterwards(self, db):
        """SQLite rebuilds the file in place and some versions keep a stale cache, so the
        connector drops the connection. If that ever stopped happening, the failure would
        appear as a corrupt read somewhere else entirely."""
        db.compact()
        db.execute("INSERT INTO demo (v) VALUES ('after')")
        db.commit()
        assert db.fetchone("SELECT COUNT(*) FROM demo WHERE v = 'after'")[0] == 1


class TestOptimizeIsTheCheapHalf:

    def test_it_leaves_the_data_alone(self, db):
        db.optimize()
        assert db.fetchone('SELECT COUNT(*) FROM demo')[0] == 2000

    def test_it_builds_the_statistics_the_planner_reads(self, db):
        """ANALYZE's whole output is `sqlite_stat1`. Without it the call could be a silent
        no-op and every test here would still pass."""
        db.optimize()
        assert db.fetchone(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_stat1'")[0] == 1

    def test_it_does_not_rewrite_the_file(self, db):
        """The distinction the two actions rest on. If optimize also compacted, the warning
        on the other button would be a lie by omission."""
        db.execute('DELETE FROM demo')
        db.commit()
        db.checkpoint()
        before = database_size(db)
        db.optimize()
        # Allowed to GROW (sqlite_stat1 is new pages); must not collapse to a compacted file.
        assert database_size(db) >= before * 0.9


class TestEveryEngineAnswersBothCalls:
    """The base class defines them as no-ops so an engine that cannot do one still answers.
    A missing method would be an AttributeError raised from inside a route."""

    def test_the_contract_exists(self):
        for name in ('vacuum', 'compact', 'optimize', 'list_tables'):
            assert callable(getattr(BaseConnector, name, None)), f'{name} left the contract'

    def test_every_connector_implements_them(self):
        """Read as source, not imported: mysql and postgresql need their drivers installed."""
        for mod, expect in (('mysql.py', ('compact', 'optimize', 'list_tables')),
                            ('postgresql.py', ('compact', 'optimize', 'list_tables')),
                            ('sqlite.py', ('compact', 'optimize', 'list_tables'))):
            src = io.open(os.path.join(SRC, 'lib', 'db', mod), encoding='utf-8').read()
            for name in expect:
                assert f'def {name}(' in src, f'{mod} does not implement {name}'

    def test_routine_vacuum_is_not_the_locking_one(self):
        """PostgreSQL is where this matters: `vacuum` runs automatically after History prunes
        rows, so pointing it at VACUUM FULL would let a background step take an ACCESS
        EXCLUSIVE lock on every table and freeze the panel."""
        import re as _re                                          # noqa: PLC0415
        src = io.open(os.path.join(SRC, 'lib', 'db', 'postgresql.py'), encoding='utf-8').read()

        def _method(name):
            """Just that method — up to the next `def`, not up to some later one. Slicing
            between two named methods breaks the moment a third is added between them, and a
            guard that reads a neighbour's docstring fails for a reason that is not the bug
            it exists to catch."""
            m = _re.search(r'^    def ' + name + r'\(.*?(?=^    def |\Z)', src, _re.S | _re.M)
            assert m, f'{name}() is gone from the PostgreSQL connector'
            return m.group(0)

        assert 'VACUUM FULL' not in _method('vacuum'), \
            'the automatic post-delete vacuum now locks everything'
        assert 'VACUUM FULL' in _method('compact'), \
            'compact stopped doing the only thing that frees space'

    def test_mysql_names_its_tables_one_at_a_time(self):
        """MySQL has no database-wide form. One comma-separated statement fails entirely on
        the first table that refuses it, leaving the admin unable to tell how far it got."""
        src = io.open(os.path.join(SRC, 'lib', 'db', 'mysql.py'), encoding='utf-8').read()
        per = src[src.index('def _per_table('):src.index('def _dbg_maintenance(')]
        assert 'self.list_tables()' in per, 'it no longer asks the catalog for the tables'
        assert 'cur.fetchall()' in per, \
            'the result set is left unread — the next query fails with "commands out of sync"'


class TestSizeReportingIsHonest:

    def test_unknown_is_not_zero(self, tmp_path):
        """A managed PostgreSQL can refuse pg_database_size to a non-superuser. The operation
        still succeeded; it just cannot say by how much. Reported as None so the UI says
        nothing, because 0 would render as "freed everything"."""
        class Mute(SQLiteConnector):
            pass
        conn = Mute(':memory:')
        assert database_size(conn) is None
        conn.close()

    def test_it_counts_the_wal_too(self, db):
        """Counting only the main file would report a drop that had merely moved into the
        write-ahead log — a reclaim that never happened."""
        src = io.open(os.path.join(SRC, 'lib', 'core', 'config', 'service.py'),
                      encoding='utf-8').read()
        fn = src[src.index('def database_size('):]
        assert "'-wal'" in fn and "'-shm'" in fn


class TestTheEndpointIsGuarded:

    def test_it_demands_its_own_permission(self, client):
        """Not config_edit: editing a setting and freezing the database for the length of a
        rewrite are not the same authority."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        src = io.open(os.path.join(SRC, 'lib', 'core', 'config', 'routes.py'),
                      encoding='utf-8').read()
        assert "_perm_required('db_maintenance')" in src

    def test_the_operation_is_looked_up_not_called_by_name(self):
        """`op` comes from the URL. `getattr(connector, op)()` would turn this endpoint into a
        way to invoke any method the connector happens to have."""
        src = io.open(os.path.join(SRC, 'lib', 'core', 'config', 'routes.py'),
                      encoding='utf-8').read()
        fn = src[src.index('def api_db_maintenance('):]
        assert '_DB_OPS.get(op)' in fn
        assert 'getattr(conn, op)' not in fn, 'the URL now picks the method to run'

    def test_an_unknown_operation_is_refused(self, client):
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        assert client.post('/api/v1/config/db/drop_everything').status_code in (400, 403)

    def test_optimize_runs_and_is_audited(self, admin, client):
        """Through the real route. Audited like any operator action — with the before/after
        numbers, because "compacted" with nothing to check it against is a claim, not a
        record, and whether there WAS anything to reclaim is the reason to run it."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        r = client.post('/api/v1/config/db/optimize')
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['ok'] is True and body['operation'] == 'optimize'
        assert [e for e in admin._audit_log if e['event'] == 'db_optimized']

    def test_compact_runs_and_is_audited(self, admin, client):
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        assert client.post('/api/v1/config/db/compact').status_code == 200
        entry = [e for e in admin._audit_log if e['event'] == 'db_compacted'][-1]
        assert entry['detail']['ok'] is True
        assert 'bytes_before' in entry['detail'], 'the record does not say what it reclaimed'




class TestOptimizeReportsRealProgress:
    """A single call that returns only when everything is done says nothing while it works,
    and on a large database that silence is indistinguishable from a hang. Walking the tables
    one at a time makes each tick mean THAT table finished — so a run that stalls shows which
    table it stalled on, which a percentage bar never can.
    """

    def test_every_engine_can_analyze_one_table(self, db):
        """The premise. Without per-table analysis there is no honest progress to report."""
        db.optimize('demo')
        assert db.fetchone(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_stat1'")[0] == 1

    def test_the_whole_database_form_still_works(self, db):
        db.optimize()
        assert db.fetchone('SELECT COUNT(*) FROM demo')[0] == 2000

    def test_the_table_list_comes_from_the_catalog(self, client):
        """Not from the TableSpec declarations: a module table created at runtime is as real
        as a declared one, and a list that omitted it would tick to the end with work left."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        r = client.get('/api/v1/config/db/targets/optimize')
        assert r.status_code == 200
        body = r.get_json()
        assert body['divisible'] is True
        assert body['targets'] and 'config' in body['targets'], body

    def test_one_table_can_be_optimized_through_the_route(self, client):
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        table = client.get('/api/v1/config/db/targets/optimize').get_json()['targets'][0]
        r = client.post('/api/v1/config/db/optimize', json={'table': table})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['table'] == table

    def test_a_table_name_is_checked_against_the_catalog(self, client):
        """It is interpolated into SQL — an identifier cannot be a bound parameter — so
        accepting whatever arrived would be an injection point. Quoting is not a reason to
        skip the check; it is the reason the check has to be the thing that decides."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        for bad in ('nonexistent', 'config; DROP TABLE config', 'config"'):
            r = client.post('/api/v1/config/db/optimize', json={'table': bad})
            assert r.status_code == 400, f'{bad!r} was accepted'

    def test_compacting_one_table_is_refused(self, client):
        """Per-table exists so progress can be reported for the cheap operation. A compaction
        is one rewrite of the whole store on two of the three engines, and offering it per
        table would imply a granularity the engines do not have."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        table = client.get('/api/v1/config/db/targets/optimize').get_json()['targets'][0]
        assert client.post('/api/v1/config/db/compact',
                           json={'table': table}).status_code == 400

    def test_a_per_table_step_writes_no_audit_entry(self, admin, client):
        """The run is ONE operator action. A row per table would bury the entry it belongs
        to — thirty lines saying nothing each, in the log read to find what changed."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        table = client.get('/api/v1/config/db/targets/optimize').get_json()['targets'][0]
        before = len([e for e in admin._audit_log if e['event'] == 'db_optimized'])
        client.post('/api/v1/config/db/optimize', json={'table': table})
        assert len([e for e in admin._audit_log if e['event'] == 'db_optimized']) == before
        # …and the closing call, with no table, is what records the run.
        client.post('/api/v1/config/db/optimize', json={})
        assert len([e for e in admin._audit_log if e['event'] == 'db_optimized']) == before + 1

    def test_the_dialog_cannot_be_dismissed_mid_run(self):
        """Closing the window would not stop the work, only stop you seeing it."""
        body = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'modals', '_db_optimize.html'), encoding='utf-8').read()
        assert 'data-bs-backdrop="static"' in body

    def test_the_tick_follows_the_response_not_a_timer(self):
        body = io.open(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'cfg', '_db_maintenance.html'), encoding='utf-8').read()
        run = body[body.index('async function _dbOptimizeRun'):]
        assert 'await apiPost' in run, 'it stopped waiting for each table'
        assert 'bi-check-circle-fill' in run and 'bi-x-circle-fill' in run, \
            'a table that failed looks the same as one that succeeded'
        assert '_dbOptAbort' in run, 'the run can no longer be stopped'


class TestTheAuditEntrySaysWhatHappened:
    """Reported from the audit screen: the entry was an event name and `ok: true`. True, and
    useless — it records that something happened rather than what, and the person who opens it
    is asking exactly the question it does not answer.
    """

    def test_the_run_records_every_table_it_walked(self, admin, client):
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        tables = client.get('/api/v1/config/db/targets/optimize').get_json()['targets'][:3]
        client.post('/api/v1/config/db/optimize', json={'results': [
            {'table': t, 'ok': True} for t in tables]})
        d = [e for e in admin._audit_log if e['event'] == 'db_optimized'][-1]['detail']
        assert d['tables_total'] == len(tables)
        assert d['tables_ok'] == len(tables)
        assert d['tables_failed'] == 0

    def test_a_failed_table_is_named_with_its_error(self, admin, client):
        """The one thing worth reading in a run of thirty-three."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        table = client.get('/api/v1/config/db/targets/optimize').get_json()['targets'][0]
        client.post('/api/v1/config/db/optimize', json={'results': [
            {'table': table, 'ok': False, 'error': 'locked'}]})
        d = [e for e in admin._audit_log if e['event'] == 'db_optimized'][-1]['detail']
        assert d['tables_failed'] == 1
        assert d['failed'][0] == {'table': table, 'error': 'locked'}

    def test_the_client_cannot_write_whatever_it_likes(self, admin, client):
        """The summary comes from the browser — it is the only witness to a run the server
        answers one table at a time. That makes it a claim, and the audit log is not a place
        anyone gets to put arbitrary strings: a name this operation could not have walked is
        dropped, and errors are cut short."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        client.post('/api/v1/config/db/optimize', json={'results': [
            {'table': 'not_a_table', 'ok': False, 'error': 'x' * 5000},
            {'table': '<script>', 'ok': True}]})
        d = [e for e in admin._audit_log if e['event'] == 'db_optimized'][-1]['detail']
        assert 'failed' not in d and 'tables_total' not in d, d

    def test_a_long_failure_list_is_cut(self):
        """A run against a broken database could fail every table, and an entry reproducing
        four hundred error strings is not a record — it is a denial of service against the
        person reading the log."""
        from lib.core.config.service import summarize_run          # noqa: PLC0415
        known = [f't{i}' for i in range(150)]
        out = summarize_run([{'table': t, 'ok': False, 'error': 'e'} for t in known],
                            known, 100)
        assert out['tables_failed'] == 150
        assert len(out['failed']) == 100, 'the cut moved without the count following it'
        assert out['failed_truncated'] == 50

    def test_a_long_success_list_is_cut_too(self):
        """Both sides are listed now, so both need the same ceiling — a database with a
        thousand module tables would otherwise put a thousand names in one entry."""
        from lib.core.config.service import summarize_run          # noqa: PLC0415
        known = [f't{i}' for i in range(150)]
        out = summarize_run([{'table': t, 'ok': True} for t in known], known, 100)
        assert out['tables_ok'] == 150
        assert len(out['ok_tables']) == 100
        assert out['ok_truncated'] == 50

    def test_the_ceiling_is_configurable(self):
        """`web_admin|audit_detail_max_items`. A hardcoded 100 is a guess about somebody
        else's install: the number of tables is not bounded — modules create their own at
        runtime — so what counts as "too long to read" is theirs to decide."""
        from lib.config.spec import CFG_BY_PATH                     # noqa: PLC0415
        from lib.core.config.service import summarize_run           # noqa: PLC0415
        cfg = CFG_BY_PATH['web_admin|audit_detail_max_items']
        assert cfg.default == 100 and cfg.env == 'SS_AUDIT_DETAIL_MAX_ITEMS'
        known = [f't{i}' for i in range(5)]
        rows = [{'table': t, 'ok': True} for t in known]
        assert len(summarize_run(rows, known, 2)['ok_tables']) == 2

    def test_zero_turns_the_names_off_but_never_the_counts(self):
        """0 = off, the usual meaning of 0 in a limit. What it must NOT do is empty the entry:
        the counts say the run happened and how it went, and without them the record would be
        indistinguishable from a run that covered nothing."""
        from lib.core.config.service import summarize_run           # noqa: PLC0415
        known = [f't{i}' for i in range(5)]
        out = summarize_run([{'table': t, 'ok': True} for t in known], known, 0)
        assert 'ok_tables' not in out and 'ok_truncated' not in out
        assert out['tables_total'] == 5 and out['tables_ok'] == 5

    def test_a_clean_run_still_names_its_tables(self):
        """The report that started this: with zero failures the entry showed counts and
        nothing else — "33 of 33" answers a question nobody asked. What the reader wants is
        WHICH tables it covered."""
        from lib.core.config.service import summarize_run          # noqa: PLC0415
        out = summarize_run([{'table': 'audit', 'ok': True}, {'table': 'config', 'ok': True}],
                            ['audit', 'config'])
        assert out['ok_tables'] == ['audit', 'config']

    def test_clearing_the_check_state_says_how_much_it_erased(self, admin, client):
        """"State cleared" records that a thing happened. The gap between clearing four rows
        and four thousand is the whole question somebody has when they find the entry."""
        from tests.conftest import _login                          # noqa: PLC0415
        _login(client)
        r = client.delete('/api/v1/modules/status')
        assert r.status_code == 200, r.get_json()
        assert 'rows_deleted' in r.get_json()
        d = [e for e in admin._audit_log if e['event'] == 'status_cleared'][-1]['detail']
        assert 'rows_deleted' in d, d

    def test_the_maintenance_events_are_prefixed(self):
        """They sat among two hundred audit event names with nothing saying where they came
        from — one read "Estado borrado", which names neither the section nor the subject."""
        from lib.i18n.lang import en_EN, es_ES                     # noqa: PLC0415
        for name, table, prefix in (('es_ES', es_ES.LANG, 'Mantenimiento:'),
                                    ('en_EN', en_EN.LANG, 'Maintenance:')):
            for event in ('db_optimized', 'db_compacted', 'status_cleared'):
                label = table['audit_events'][event]
                assert label.startswith(prefix), f'{name}/{event}: {label!r}'
