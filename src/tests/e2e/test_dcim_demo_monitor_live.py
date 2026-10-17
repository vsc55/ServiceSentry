#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The demo's monitoring side on the real engines: MariaDB/MySQL and PostgreSQL.

`tests/integration/test_dcim_demo_monitor.py` proves it on SQLite. Here the same install and
removal run on a panel booted against each live engine (``SS_TEST_*``, see
`tests/e2e/test_db_portability_live.py`): devices created and bound, simulated checks saved in
the module tables, their state rows and their history written, the states the board derives
the demo's — and removing leaves no device, check, state row, series or credential of it.
Serial only (``-n0``); the tables the panel created are dropped afterwards, nothing else.
"""

import json
import os
from unittest import mock

import pytest

try:
    from lib.web_admin import WebAdmin
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

from tests.e2e.test_db_portability_live import (_mariadb_cfg, _mysql_cfg,  # noqa: E402
                                                _pg_cfg)


@pytest.fixture(params=['mysql', 'mariadb', 'postgresql'])
def engine(request):
    if int(os.environ.get('PYTEST_XDIST_WORKER_COUNT', '1')) > 1:
        pytest.skip('live DB tests must run serially - use -n0')
    cfg = {'mysql': _mysql_cfg, 'mariadb': _mariadb_cfg, 'postgresql': _pg_cfg}[request.param]()
    if cfg is None:
        pytest.skip(f'{request.param} not configured')
    from lib.db import get_connector
    try:
        db = get_connector(cfg)
        db.fetchone('SELECT 1')
        pre = set(db.list_tables())
        db.commit()
        db.close()
    except Exception as exc:  # pylint: disable=broad-except
        pytest.skip(f'{request.param} unreachable: {exc}')
    return cfg, pre


def test_install_and_remove_on_the_engine(engine, tmp_path):
    from lib.core.dcim import demo, demo_monitor
    from lib.core.dcim import service as dcim_svc
    from lib.core.devices import service as devices_svc
    from lib.core.notify import registry

    cfg, pre = engine
    env = {'SS_DB_DRIVER': cfg['driver'], 'SS_DB_HOST': cfg['host'],
           'SS_DB_PORT': str(cfg['port']), 'SS_DB_NAME': cfg['name'],
           'SS_DB_USER': cfg['user'], 'SS_DB_PASSWORD': cfg['password']}
    conf, var = tmp_path / 'conf', tmp_path / 'var'
    conf.mkdir()
    var.mkdir()
    (conf / 'config.json').write_text(json.dumps({
        'monitoring': {'timer_check': 300, 'autostart': False},
        'events': {'autostart': False}, 'syslog': {'autostart': False}}), encoding='utf-8')
    with mock.patch.dict(os.environ, env):
        wa = WebAdmin(str(conf), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        wa._modules_dir = os.path.join(
            os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0], 'watchfuls')
        try:
            with mock.patch.object(demo_monitor, 'HISTORY_HOURS', 2), \
                    mock.patch.object(registry, 'channels', lambda: {}):
                made = demo.build(wa._dcim_store, app=wa, var_dir=str(var))
            ctx = demo.DemoContext(wa._dcim_store, app=wa, words=demo.texts(''),
                                   created={'sites': {k: made[k] for k in demo.UID_KEYS}})
            rows = demo_monitor._painted(ctx)
            estados = devices_svc._device_statuses(wa)
            assert len(rows) > 300
            for r in rows:
                it = wa._dcim_store.items.get(r['item']['uid'])
                assert dcim_svc.item_state(it, estados) == r['state'], r['label']
            assert wa._check_state_store.count() >= len(rows)
            assert any(s['module'] == 'ping' for s in wa._history.get_index())
            # The power: every UPS and PDU bound to its device, on this engine too.
            s = wa._dcim_store
            assert s.pdus.list() and all(p['device_uid'] for p in s.pdus.list())
            assert all(x['device_uid'] for x in s.sources.list() if x['kind'] == 'ups')
            # A cycle on the engine: the batched history write (`record_many`) and the
            # simulated devices on their cadence (all due: a sweep long after the last).
            from lib.core.snmp import simulated_agent
            antes = sum(int(x.get('count') or 0) for x in wa._history.get_index())
            with mock.patch.object(registry, 'channels', lambda: {}), \
                    mock.patch.object(simulated_agent, 'is_due', lambda *_a, **_k: True):
                _res, errs = wa._run_checks(['ping', 'snmp'], timeout=900)
            assert not errs
            despues = sum(int(x.get('count') or 0) for x in wa._history.get_index())
            assert despues - antes > len(rows)

            claves = {k for _m, _c, k, _i in demo_monitor._demo_items(wa._load_modules())}
            with mock.patch.object(registry, 'channels', lambda: {}):
                assert demo.remove(wa._dcim_store, app=wa, var_dir=str(var)) == 6
            assert not [d for d in wa._devices_store.list(decrypt=False)
                        if d['source'] == 'demo']
            assert not list(demo_monitor._demo_items(wa._load_modules()))
            def _item(key):
                return str(key or '').split('/')[0].rsplit('_', 1)[0]
            assert not [k for m in wa._check_state_store.as_status_dict().values() for k in m
                        if k in claves or _item(k) in claves]
            assert not [s for s in wa._history.get_index()
                        if s.get('key') in claves or _item(s.get('key')) in claves]
            assert not [c for c in wa._credentials_store.list(decrypt=False)
                        if c['name'].startswith('Demo · ')]
        finally:
            conn = wa._db_connector
            try:
                for t in set(conn.list_tables()) - pre:
                    conn.execute(f'DROP TABLE IF EXISTS {conn.quote_ident(t)}')
                conn.commit()
            except Exception:  # pylint: disable=broad-except
                pass
            finally:
                try:
                    conn.close()
                except Exception:  # pylint: disable=broad-except
                    pass
