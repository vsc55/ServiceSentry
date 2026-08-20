#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Infrastructure — the fleet as it IS, beside the registry that says what it should be.

System › Infrastructure answers "what have I declared": machines, clusters, which module
watches what, with which credential. It is edited, and it is where a change changes the
installation. What it could never answer is the other half — **what are those machines
doing** — because the panel arranged that by CHECK (Status) and by SERIES (History), and
never by machine.

This section is that arrangement, and it is read-only by construction: there is no write
route in the domain, so it can be handed to whoever watches the screens without handing over
the registry with it.

Most of this file is about the two things that are easy to get wrong when a screen composes
other people's data:

* **it must not leak more than it shows.** A host record carries `profiles` — the bound
  credential of every protocol that reaches the machine — and the payload is a whitelist
  projection rather than "the record minus a few keys", which is one added field away from
  shipping them;
* **it must not invent facts.** The state comes from the hosts domain, the values from the
  modules, and a number is a measurement only when the module that produced it said so.
"""

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from werkzeug.security import generate_password_hash

from lib.core.infra import service as infra_svc

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')

_HOST = {
    'name': 'nas-1', 'address': '10.0.0.9', 'tags': ['prod'],
    'profiles': {'ssh': {'user': 'root', 'ssh_password': 'p@ss', 'port': 22}},
}


def _mkhost(client, **over):
    body = dict(_HOST)
    body.update(over)
    r = client.post('/api/v1/hosts', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


def _as(admin, username, role='viewer', password='pw-secret'):
    admin._users[username] = {'uid': f'u-{username}', 'role': role, 'enabled': True,
                              'password_hash': generate_password_hash(password)}
    c = admin.app.test_client()
    c.post('/login', data={'username': username, 'password': password}, follow_redirects=True)
    return c


class TestTheFleet:

    def test_it_needs_a_session(self, client):
        assert client.get('/api/v1/infra/hosts').status_code == 401

    def test_it_lists_the_machines(self, client):
        _login(client)
        uid = _mkhost(client)
        data = client.get('/api/v1/infra/hosts').get_json()
        row = next(h for h in data['hosts'] if h['uid'] == uid)
        assert row['name'] == 'nas-1' and row['address'] == '10.0.0.9'
        assert row['tags'] == ['prod']

    def test_it_never_carries_the_credentials(self, client):
        """The registry masks the secret values inside `profiles`; this section does not ship
        `profiles` AT ALL. A screen that only shows state has no reason to carry the bound
        credential of every protocol that reaches the machine, and a projection written as a
        whitelist cannot start carrying it because somebody added a field."""
        _login(client)
        _mkhost(client)
        body = client.get('/api/v1/infra/hosts').data.decode()
        assert 'profiles' not in body and 'ssh_password' not in body and 'p@ss' not in body

    def test_a_machine_nobody_watches_is_its_own_state(self, client):
        """Not "ok". A host with no enabled check has no status at all, and painting it green
        is the section lying about the one thing it exists to show — so it has its own count
        in the header, where "31 OK" would have hidden it."""
        _login(client)
        _mkhost(client)
        data = client.get('/api/v1/infra/hosts').get_json()
        row = next(h for h in data['hosts'] if h['name'] == 'nas-1')
        assert row['status'] == ''
        assert data['summary']['unwatched'] >= 1

    def test_the_summary_counts_what_the_list_holds(self, client):
        _login(client)
        _mkhost(client)
        _mkhost(client, name='nas-2', address='10.0.0.10')
        data = client.get('/api/v1/infra/hosts').get_json()
        s = data['summary']
        assert s['total'] == len(data['hosts'])
        assert s['ok'] + s['warning'] + s['error'] + s['unwatched'] == s['total']


class TestOneMachine:

    def test_it_answers_with_what_it_is_and_what_it_said(self, client):
        _login(client)
        uid = _mkhost(client)
        data = client.get(f'/api/v1/infra/hosts/{uid}').get_json()
        assert data['host']['name'] == 'nas-1'
        assert data['results'] == [] and data['metrics'] == []

    def test_an_unknown_machine_is_a_404(self, client):
        _login(client)
        assert client.get('/api/v1/infra/hosts/not-a-host').status_code == 404

    def test_it_does_not_carry_the_credentials_either(self, client):
        _login(client)
        uid = _mkhost(client)
        assert 'p@ss' not in client.get(f'/api/v1/infra/hosts/{uid}').data.decode()


class TestWhoMaySeeIt:
    """`infra_view` and not `servers_view`: reading the live state and editing the registry
    that defines it are different acts, wanted by different people."""

    def test_a_role_without_the_flag_is_refused(self, admin):
        c = _as(admin, 'nobody', role='none')
        assert c.get('/api/v1/infra/hosts').status_code == 403

    def test_a_viewer_may_read_it(self, admin, client):
        _login(client)
        _mkhost(client)
        c = _as(admin, 'watcher', role='viewer')
        r = c.get('/api/v1/infra/hosts')
        assert r.status_code == 200 and r.get_json()['hosts']

    def test_the_flag_exists_and_grants_no_writing(self):
        """There is no `infra_edit`, and that is the design: what there is to change lives in
        the registry, behind the permissions the registry already has."""
        from lib.core.infra.manifest import MODULE_PERMISSIONS
        flags = [p['flag'] for p in MODULE_PERMISSIONS['permissions']]
        assert flags == ['infra_view']


class TestTheViewModel:
    """Pure functions, so the rules are checked where they are written."""

    def test_the_worst_machine_comes_first(self):
        """This list is opened when something is wrong. Alphabetical order answers "which
        machine is in trouble" by making you read every row."""
        rows = infra_svc.fleet([
            {'uid': '1', 'name': 'a', 'status': 'ok'},
            {'uid': '2', 'name': 'b', 'status': ''},
            {'uid': '3', 'name': 'c', 'status': 'error'},
            {'uid': '4', 'name': 'd', 'status': 'warning'},
        ])
        assert [r['name'] for r in rows] == ['c', 'd', 'b', 'a']

    def test_a_value_is_a_measurement_only_when_its_module_said_so(self):
        """`other_data` is a bag of whatever the module felt like recording. The section must
        not guess which key is a measurement nor invent a name for it — it reads the module's
        own `__history__` declaration, the same one that makes the value chartable."""
        results = [{'module': 'cpu', 'key': 'k1', 'name': 'CPU',
                    'data': {'used': 41.5, 'model': 'Xeon', 'cores': 8}, 'ts': 't'}]
        fields = {'cpu': {'used': {'label': 'Uso', 'unit': '%'}}}
        out = infra_svc.metrics(results, fields)
        assert [m['field'] for m in out] == ['used']
        assert out[0]['value'] == 41.5 and out[0]['unit'] == '%' and out[0]['label'] == 'Uso'

    def test_a_declared_field_that_is_not_a_number_is_not_charted(self):
        """A string under a declared key would reach a chart axis as a label nobody can
        plot."""
        results = [{'module': 'cpu', 'key': 'k1', 'name': 'CPU', 'data': {'used': 'n/a'}}]
        assert infra_svc.metrics(results, {'cpu': {'used': {'unit': '%'}}}) == []

    def test_a_boolean_is_not_a_measurement(self):
        """`True` is an int in Python, so a status flag under a declared key would plot as a
        line at 1 and read as data."""
        results = [{'module': 'x', 'key': 'k', 'name': 'n', 'data': {'up': True}}]
        assert infra_svc.metrics(results, {'x': {'up': {'unit': ''}}}) == []

    def test_the_metric_carries_the_coordinates_of_its_series(self):
        """So the screen can chart it without knowing anything about the module — and without
        composing (module, key) itself, which is how two places end up disagreeing about how a
        series is addressed."""
        results = [{'module': 'cpu', 'key': 'k1', 'name': 'CPU', 'data': {'used': 1}}]
        out = infra_svc.metrics(results, {'cpu': {'used': {}}})
        assert out[0]['series'] == {'module': 'cpu', 'key': 'k1', 'field': 'used'}
