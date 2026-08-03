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


Split by category: this file holds the tests that drive the Flask app; the rest of the original
``test_db_maintenance.py`` lives in ``tests/unit/test_db_maintenance.py``."""

import io
import os

import pytest

from lib.db.sqlite import SQLiteConnector

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


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


