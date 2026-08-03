#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security audit of the panel booted against a REAL engine — injection, and access control.

The regression suite proves these properties on SQLite by driving the routes. This runs the
same attacks against MySQL, MariaDB and PostgreSQL because two of the three failure modes only
show on a real server:

* **Injection.** A parameterised query stores ``' OR '1'='1`` as a literal string; a query
  built by concatenation sends the quote to the engine, which answers with a syntax error — a
  500. SQLite forgives quoting MySQL rejects, so a concatenation bug can pass on SQLite and
  fail in production. Here a 500 on any string field is treated as a finding, and a canary
  table's survival against stacked ``; DROP TABLE`` is the proof no statement was smuggled in.

* **Access control and escalation.** These are engine-independent, but running them here means
  the guarantee is checked end-to-end on the database an install actually uses: anonymous
  callers get nothing, a viewer mutates nothing, and a ``users_add`` holder can neither mint an
  admin nor promote itself.

Opt-in and skipped without the ``SS_TEST_<engine>_HOST`` variables, exactly like
``test_db_portability_live.py`` — and run SERIALLY (``-n0``): they boot a real panel and share
scratch databases with fixed table names.

    .venv/Scripts/python -m pytest -n0 -q tests/test_security_live.py

Each attack asserts the exact rejection code, and each role carries a POSITIVE control (the
thing it IS allowed to do), so a login that silently failed cannot make the audit pass
vacuously — the failure this whole file exists to avoid.
"""
from __future__ import annotations

import json
import os

import pytest

try:
    from lib.web_admin import WebAdmin           # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")

# ``engine -> (env prefix, driver, default port)``. MariaDB has its own prefix because it is
# not MySQL — same driver, but the DEFAULT-on-TEXT and quoting behaviour that injection probes
# lean on differ, so "it passed on MySQL" is not "it passed on MariaDB".
_ENGINES = {
    'mysql':      ('MYSQL',   'mysql',      '3306'),
    'mariadb':    ('MARIADB', 'mysql',      '3306'),
    'postgresql': ('PG',      'postgresql', '5432'),
}


def _cfg(engine: str):
    prefix, driver, default_port = _ENGINES[engine]
    host = os.environ.get(f'SS_TEST_{prefix}_HOST')
    if not host:
        return None
    return {
        'driver': driver, 'host': host,
        'name':     os.environ.get(f'SS_TEST_{prefix}_DB', 'test'),
        'user':     os.environ.get(f'SS_TEST_{prefix}_USER', 'root'),
        'password': os.environ.get(f'SS_TEST_{prefix}_PASSWORD', ''),
        'port': int(os.environ.get(f'SS_TEST_{prefix}_PORT', default_port)),
    }


@pytest.fixture(params=list(_ENGINES))
def panel(request, tmp_path):
    """A real panel on the parametrised engine, admin logged in, torn down cleanly.

    Boots the whole WebAdmin through ``SS_DB_*`` — the path a Docker deployment uses — so the
    audit exercises exactly what ships. Skips when the engine is not configured, and refuses
    to run under xdist: fixed table names would collide between workers.
    """
    if int(os.environ.get('PYTEST_XDIST_WORKER_COUNT', '1')) > 1:
        pytest.skip('live security tests must run serially - use -n0')
    cfg = _cfg(request.param)
    if cfg is None:
        pytest.skip(f'{request.param} not configured (set SS_TEST_'
                    f'{_ENGINES[request.param][0]}_HOST)')

    from lib.db import get_connector

    # Snapshot the schema BEFORE booting, through a throwaway connector that is then closed —
    # an open one holds a transaction, and the teardown DROPs would wait on its locks for ever
    # (the deadlock the portability suite already learned). Teardown removes only what the
    # panel created, never a table that was already there: the configured database may be
    # shared, and the PostgreSQL default is `postgres`, the cluster's own.
    probe = get_connector(cfg)
    try:
        probe.fetchone('SELECT 1')
    except Exception as exc:                          # pylint: disable=broad-except
        pytest.skip(f'{request.param} unreachable: {exc}')
    pre_existing = set(probe.list_tables())
    probe.commit()
    probe.close()

    env = {'SS_DB_DRIVER': cfg['driver'], 'SS_DB_HOST': cfg['host'],
           'SS_DB_PORT': str(cfg['port']), 'SS_DB_NAME': cfg['name'],
           'SS_DB_USER': cfg['user'], 'SS_DB_PASSWORD': cfg['password']}
    conf, var = tmp_path / 'conf', tmp_path / 'var'
    conf.mkdir()
    var.mkdir()
    (conf / 'config.json').write_text(json.dumps({}), encoding='utf-8')

    from unittest import mock
    with mock.patch.dict(os.environ, env):
        wa = WebAdmin(str(conf), 'admin', 'secret', str(var),
                      pw_require_upper=False, pw_require_digit=False)
        wa._csrf_enabled = False          # CSRF has its own suite; here we attack the API
        try:
            admin = wa.app.test_client()
            admin.post('/login', data={'username': 'admin', 'password': 'secret'},
                       follow_redirects=True)
            assert admin.get('/api/v1/me').get_json().get('username') == 'admin'
            yield _Panel(wa, admin)
        finally:
            conn = wa._db_connector
            try:
                for t in set(conn.list_tables()) - pre_existing:
                    conn.execute(f'DROP TABLE IF EXISTS {conn.quote_ident(t)}')
                conn.commit()
            except Exception:             # pylint: disable=broad-except
                pass
            finally:
                try:
                    conn.close()
                except Exception:         # pylint: disable=broad-except
                    pass


class _Panel:
    def __init__(self, wa, admin):
        self.wa = wa
        self.admin = admin

    def client(self, username=None, password=None):
        c = self.wa.app.test_client()
        if username:
            c.post('/login', data={'username': username, 'password': password},
                   follow_redirects=True)
        return c


# ── Injection ──────────────────────────────────────────────────────────────────────
_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE sec_canary; --",
    "' OR 1=1 --",
    "admin'--",
    "x'; DROP TABLE sec_canary; --",
    "' UNION SELECT username, password_hash, 1, 1, 1, 1, 1, 1 FROM users --",
    "'||(SELECT password_hash FROM users LIMIT 1)||'",
    "1; DROP TABLE sec_canary",
    "' AND SLEEP(3) --",
]


def test_no_payload_reaches_the_engine_as_sql(panel):
    """Every string field, on a real engine, must store the payload and never execute it."""
    wa, admin = panel.wa, panel.admin
    db = wa._db_connector

    db.execute('DROP TABLE IF EXISTS sec_canary')
    db.execute('CREATE TABLE sec_canary (id INTEGER)')
    db.execute('INSERT INTO sec_canary VALUES (1)')
    db.commit()

    server_errors = []
    for i, p in enumerate(_PAYLOADS):
        posts = [
            ('/api/v1/users', {'username': p, 'password': 'testpass1', 'role': 'viewer'}),
            ('/api/v1/users', {'username': f'inj{i}', 'password': 'testpass1',
                               'role': 'viewer', 'display_name': p, 'email': p}),
            ('/api/v1/groups', {'name': p, 'roles': []}),
            ('/api/v1/roles', {'name': p, 'permissions': ['users_view']}),
            ('/api/v1/hosts', {'name': p, 'address': p}),
            ('/api/v1/credentials', {'name': p, 'kind': 'ssh', 'username': 'r', 'password': 'x'}),
        ]
        for path, body in posts:
            r = admin.post(path, json=body)
            if r.status_code >= 500:
                server_errors.append(f'{path} {p!r} -> {r.status_code}')
        # read filters, in case any reaches SQL unparameterised
        admin.get(f'/api/v1/audit?q={p}')
        admin.get(f'/api/v1/history?module={p}&key={p}')

    canary_alive = 'sec_canary' in db.list_tables()
    users_intact = db.fetchone('SELECT COUNT(*) FROM users')[0] > 0
    # The payloads that pass validation must be STORED verbatim — parameterised, not executed.
    stored = db.fetchone("SELECT COUNT(*) FROM users WHERE username LIKE ? OR display_name LIKE ?",
                         ('%OR%', '%DROP%'))[0]
    db.execute('DROP TABLE IF EXISTS sec_canary')
    db.commit()

    assert not server_errors, 'a payload reached the engine as SQL (500s): ' + '; '.join(server_errors)
    assert canary_alive, 'a stacked DROP took the canary table — injection succeeded'
    assert users_intact, 'the users table did not survive the payloads'
    assert stored > 0, 'no payload was stored — the harness never reached the write path'


# ── Access control and escalation ───────────────────────────────────────────────────
def test_access_control_and_escalation_hold(panel):
    """Anonymous reads nothing, a viewer writes nothing, and users_add cannot escalate — each
    with the exact rejection code, and each role proven able to do what it MAY, so a login
    that silently failed cannot pass this vacuously."""
    wa, admin = panel.wa, panel.admin
    admin.post('/api/v1/users', json={'username': 'viewer1', 'password': 'testpass1',
                                      'role': 'viewer'})
    admin.post('/api/v1/roles', json={'name': 'adder',
                                      'permissions': ['users_view', 'users_add']})
    admin.post('/api/v1/users', json={'username': 'adder1', 'password': 'testpass1',
                                      'role': 'adder'})
    admin_uid = wa._role_name_to_uid('admin')
    admin_grp = next((gid for gid, g in wa._groups.items()
                      if g.get('name') == 'Administrators'), None)

    problems = []

    def must(cond, msg):
        if not cond:
            problems.append(msg)

    # 1 — anonymous
    anon = panel.client()
    for path in ('/api/v1/users', '/api/v1/roles', '/api/v1/config', '/api/v1/credentials',
                 '/api/v1/hosts', '/api/v1/audit'):
        must(anon.get(path).status_code in (401, 302), f'anon read {path} without a session')
    must(anon.post('/api/v1/users', json={'username': 'a', 'password': 'testpass1'}).status_code
         in (401, 302), 'anon created a user')

    # 2 — viewer: read-only
    v = panel.client('viewer1', 'testpass1')
    must(v.get('/api/v1/users').status_code == 200, 'a viewer could not even READ users (login broke?)')
    for method, path, body in [
        ('post', '/api/v1/users', {'username': 'vx', 'password': 'testpass1', 'role': 'viewer'}),
        ('post', '/api/v1/roles', {'name': 'vr', 'permissions': ['users_view']}),
        ('post', '/api/v1/hosts', {'name': 'vh', 'address': '1.1.1.1'}),
        ('put',  '/api/v1/config', {'monitoring': {'timer_check': 1}}),
        ('delete', '/api/v1/users/admin', None),
    ]:
        r = getattr(v, method)(path, json=body) if body else getattr(v, method)(path)
        must(r.status_code == 403, f'viewer did {method.upper()} {path} -> {r.status_code}')

    # 3 — users_add: positive control, then escalation must fail
    a = panel.client('adder1', 'testpass1')
    must(a.post('/api/v1/users', json={'username': 'legit', 'password': 'testpass1',
                                       'role': 'viewer'}).status_code == 201,
         'users_add could not create a normal user (its login/role is not real)')
    must(a.post('/api/v1/users', json={'username': 'bd', 'password': 'testpass1',
                                       'role': admin_uid}).status_code == 403,
         'ESCALATION: users_add minted an admin account')
    if admin_grp:
        must(a.post('/api/v1/users', json={'username': 'bd2', 'password': 'testpass1',
                                           'role': 'viewer', 'groups': [admin_grp]}).status_code
             == 403, 'ESCALATION: users_add put an account in Administrators')
    must(a.put('/api/v1/users/adder1', json={'role': admin_uid}).status_code == 403,
         'ESCALATION: users_add promoted itself to admin')
    must(a.post('/api/v1/roles', json={'name': 'super',
                                       'permissions': ['config_edit', 'roles_edit']}).status_code
         == 403, 'ESCALATION: users_add created a role without roles_add')

    # State-level confirmation, not just the codes.
    must('bd' not in wa._users, 'a backdoor admin account exists despite the 403')
    must(wa._users['adder1']['role'] != admin_uid, 'adder1 escalated despite the 403')

    assert not problems, 'access-control failures:\n  ' + '\n  '.join(problems)


def test_per_host_access_cannot_reach_another_host(panel):
    """IDOR: hosts are scoped per resource (``server.{uid}.view/edit/delete``), so holding a
    permission on host A must not reach host B by naming B's UID directly.

    This is the whole point of a scoped model and the exact spot where it breaks quietly: the
    LIST endpoint filters, but each per-host endpoint has to run its own check, and one that
    forgot would let anyone with a foothold on any host walk the rest by UID. Secrets make it
    worse — a leaked host carries a stored SSH credential.
    """
    wa, admin = panel.wa, panel.admin

    a_uid = admin.post('/api/v1/hosts', json={
        'name': 'host-A', 'address': '10.0.0.1'}).get_json()['uid']
    b_uid = admin.post('/api/v1/hosts', json={
        'name': 'host-B-secret', 'address': '10.0.0.2'}).get_json()['uid']

    # A role that can see ONLY host A — a well-formed per-server permission, nothing global.
    admin.post('/api/v1/roles', json={'name': 'host_a_only',
                                      'permissions': [f'server.{a_uid}.view']})
    admin.post('/api/v1/users', json={'username': 'scoped', 'password': 'testpass1',
                                      'role': 'host_a_only'})
    u = panel.client('scoped', 'testpass1')

    problems = []

    def must(cond, msg):
        if not cond:
            problems.append(msg)

    # Positive control: the scoped user CAN reach host A, and the list shows A only.
    must(u.get(f'/api/v1/hosts/{a_uid}/status').status_code == 200,
         'the scoped permission does not even grant host A (the grant is not real)')
    listing = u.get('/api/v1/hosts')
    must(listing.status_code == 200, 'scoped user cannot list at all')
    names = [h.get('name') for h in (listing.get_json() or {}).get('hosts', [])]
    must('host-A' in names, 'host A missing from the scoped list')
    must('host-B-secret' not in names, 'IDOR: host B leaked into the scoped list')

    # IDOR: every per-host endpoint aimed at B must refuse.
    must(u.get(f'/api/v1/hosts/{b_uid}/status').status_code == 403,
         'IDOR: read host B status with only server.A.view')
    must(u.put(f'/api/v1/hosts/{b_uid}',
               json={'name': 'pwned', 'address': '6.6.6.6'}).status_code == 403,
         'IDOR: edited host B with only server.A.view')
    must(u.delete(f'/api/v1/hosts/{b_uid}').status_code == 403,
         'IDOR: deleted host B with only server.A.view')

    # State-level: B is untouched — not renamed, not gone.
    after = {h['uid']: h for h in wa._hosts_store.list()}
    must(b_uid in after and after[b_uid]['name'] == 'host-B-secret',
         'host B was modified or deleted despite the 403s')

    assert not problems, 'per-host IDOR failures:\n  ' + '\n  '.join(problems)
