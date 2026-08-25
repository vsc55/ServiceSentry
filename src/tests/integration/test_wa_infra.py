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
    """`infra_view` and not `devices_view`: reading the live state and editing the registry
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

    def test_no_flag_here_is_an_edit_of_the_registry(self):
        """There is no `infra_edit`, and that is the design: what there is to CHANGE lives in
        the registry, behind the permissions the registry already has. Every flag this section
        declares is about looking at the fleet or operating the monitoring of it — asking the
        modules for fresh numbers, or saying which row is worth an alert. None stores an
        address, a credential or a name.

        The list is closed on purpose. It read `== ['infra_view', 'infra_collect']` and was
        the first thing to notice `infra_watch` arriving, which is what a closed list is for —
        a third flag has to be argued for here rather than appearing."""
        from lib.core.infra.manifest import MODULE_PERMISSIONS
        flags = [p['flag'] for p in MODULE_PERMISSIONS['permissions']]
        assert flags == ['infra_view', 'infra_collect', 'infra_watch']
        assert not any(f.endswith('_edit') or f.startswith('devices_') for f in flags), (
            'this section grew a permission over the registry, which has its own')


class TestCollectingNow:
    """The one endpoint that acts. It runs this device's checks through the SAME executor the
    scheduler cycle uses, so what lands in check state and history is produced by the one path
    that knows how to produce it — and it is gated apart from reading, because starting minutes
    of polling on somebody's fleet is not the same act as looking at yesterday's answer.

    These tests stop at the gate on purpose: what happens past it is the executor's, and it is
    tested where it lives (tests/unit/test_monitor_executor.py). A host with no bound check
    reaches the end of the route without running anything, which is what makes the whole gate
    testable without a device on the other side.
    """

    def _url(self, uid):
        return f'/api/v1/infra/hosts/{uid}/collect'

    def test_it_needs_a_session(self, client):
        assert client.post(self._url('whatever')).status_code == 401

    def test_a_viewer_may_look_but_not_collect(self, admin, client):
        """The one that matters. `viewer` holds `infra_view`, so it can read the very screen
        the button is on; if the button's endpoint rode on that flag, a read-only role would
        be able to make forty devices get polled by leaning on it."""
        _login(client)
        uid = _mkhost(client)
        c = _as(admin, 'watcher2', role='viewer')
        assert c.get(f'/api/v1/infra/hosts/{uid}').status_code == 200
        assert c.post(self._url(uid)).status_code == 403

    def test_an_editor_holds_it(self, admin, client):
        """409 and not 403: the request got past the gate and found nothing to run, which is
        the only thing this host has to say. A 403 here would mean the flag never reached the
        role that is supposed to have it."""
        _login(client)
        uid = _mkhost(client)
        c = _as(admin, 'operator', role='editor')
        r = c.post(self._url(uid))
        assert r.status_code == 409, r.get_json()

    def test_a_machine_with_no_enabled_check_has_nothing_to_collect(self, client):
        """Reporting success would draw a fresh timestamp over a screen where nothing was
        collected, which is the section telling you it looked when it did not."""
        _login(client)
        uid = _mkhost(client)
        r = client.post(self._url(uid))
        assert r.status_code == 409
        assert r.get_json()['error']

    def test_a_device_the_registry_alone_makes_a_device_has_something_to_collect(self, client):
        """The one this route got wrong. A switch or a NAS read over SNMP has no check and no
        module item: the device profiles on its own record ARE its monitoring, and the module
        samples it every cycle without anything else existing.

        What "collect now" offered was worked out from what had been RECORDED about the
        machine, which for a device that has never been sampled is nothing — so the answer was
        "this device has no check to run" about a device the scheduler collects from, and the
        button that exists to take the FIRST sample was the one thing that could not take it.
        Reported from the screen a minute after the module item was removed from a NAS.

        Not asserting a 200: what happens past this point is the executor's, and this suite has
        no modules directory to run one from. What is asserted is that the route stopped saying
        there is nothing to collect — which is the whole of the bug.
        """
        _login(client)
        uid = _mkhost(client, name='switch-1', address='10.0.0.30', profiles={
            'snmp': {'community': 'public', 'version': '2c',
                     'device_profiles': 'grp_generic'}})
        r = client.post(self._url(uid))
        assert r.status_code != 409, r.get_json()

    def test_and_a_community_with_nothing_assigned_still_has_not(self, client):
        """The other half of the same rule: SNMP reachable is not SNMP sampled. A device with
        a community and no profiles assigned is one you can ASK things of, not one anybody is
        charting — `devices_to_sample` skips it, so the button must not claim otherwise."""
        _login(client)
        uid = _mkhost(client, name='switch-2', address='10.0.0.31', profiles={
            'snmp': {'community': 'public', 'version': '2c', 'device_profiles': ''}})
        assert client.post(self._url(uid)).status_code == 409

    def test_an_unknown_machine_is_a_404(self, client):
        _login(client)
        assert client.post(self._url('not-a-host')).status_code == 404

    def test_it_refuses_a_machine_this_caller_cannot_see(self, admin, client):
        """Holding `infra_collect` says which ACT you may perform, not which machines you may
        perform it on. Both questions are asked, and the second is the registry's own rule —
        the same `devices_view` / `server.<uid>.view` narrowing the two GETs apply, so a flag
        meant to refresh your own rack never becomes a way to poll somebody else's."""
        seen = admin._hosts_store.create({**_HOST, 'name': 'mine'}, actor='admin')
        other = admin._hosts_store.create(
            {**_HOST, 'name': 'theirs', 'address': '10.0.0.11'}, actor='admin')
        role_uid = '22222222-2222-4222-8222-222222222222'
        admin._custom_roles[role_uid] = {
            'uid': role_uid, 'name': 'infra-op', 'enabled': True,
            'permissions': ['infra_view', 'infra_collect', f'server.{seen}.view'],
        }
        admin._users['infraop'] = {
            'password_hash': admin._users['admin']['password_hash'],
            'role': role_uid, 'display_name': 'I',
        }
        _login(client, 'infraop')
        # The machine it may see: past both gates, and stopped by having nothing to run.
        assert client.post(self._url(seen)).status_code == 409
        # The one it may not: refused, and refused for being invisible rather than for the flag.
        assert client.post(self._url(other)).status_code == 403


class TestCollectingFromTheWholeFleet:
    """The other question the section is asked: refresh EVERYTHING.

    The per-device button narrows its run to that device, which is what makes it quick and
    what stops it walking somebody else's rack. This is the un-narrowed run — every module
    with its whole configuration, which is what a scheduler cycle is — so the orphan prune
    stays on, because this run really did cover everything.

    What has to be got right is who may press it. `infra_collect` says which ACT you may
    perform, not which machines you may perform it on, and a run over the whole fleet polls
    machines a narrowed operator may not be allowed to see. So it asks twice.
    """

    def _url(self):
        return '/api/v1/infra/collect'

    def test_it_needs_a_session(self, client):
        assert client.post(self._url()).status_code == 401

    def test_a_viewer_may_watch_the_fleet_and_not_refresh_it(self, admin, client):
        _login(client)
        c = _as(admin, 'fleetwatcher', role='viewer')
        assert c.get('/api/v1/infra/hosts').status_code == 200
        assert c.post(self._url()).status_code == 403

    def test_holding_the_flag_is_not_enough_without_seeing_the_fleet(self, admin, client):
        """The one that matters, and the reason for the second check. An operator scoped to
        three racks holds `infra_collect` — it is what their per-device button runs on — and
        without this that flag would poll every machine in the building, including the ones
        the same session is refused a GET on two routes above.
        """
        seen = admin._hosts_store.create({**_HOST, 'name': 'theirs'}, actor='admin')
        role_uid = '33333333-3333-4333-8333-333333333333'
        admin._custom_roles[role_uid] = {
            'uid': role_uid, 'name': 'rack-op', 'enabled': True,
            'permissions': ['infra_view', 'infra_collect', f'server.{seen}.view'],
        }
        admin._users['rackop'] = {
            'password_hash': admin._users['admin']['password_hash'],
            'role': role_uid, 'display_name': 'R',
        }
        _login(client, 'rackop')
        assert client.post(self._url()).status_code == 403
        # …and the button they DO have still works, scoped the way they are.
        assert client.post(f'/api/v1/infra/hosts/{seen}/collect').status_code == 409

    def test_an_installation_with_nothing_to_run_says_so(self, admin, client, monkeypatch):
        """409 and not "done": reporting success would draw a fresh timestamp over a panel
        where nothing was collected, which is the section telling you it looked when it did
        not — the same lie the per-device button refuses to tell.

        And it is answered BEFORE the modules directory is looked at, for the reason three of
        the tests above exist: "there is nothing to collect" is true whatever happened to the
        module code, and answering it with a 500 reads as a broken server."""
        _login(client)
        monkeypatch.setattr(admin, '_load_modules', lambda: {})
        r = client.post(self._url())
        assert r.status_code == 409
        assert r.get_json()['error']

    def test_a_device_the_registry_alone_makes_a_device_is_something_to_run(self, client):
        """A fleet with nothing but a switch read over SNMP has something to collect: the
        device profiles on its own record ARE its monitoring, and there is no item anywhere
        for a list built from the module configuration to find.
        """
        _login(client)
        _mkhost(client, name='switch-fleet', address='10.0.0.40', profiles={
            'snmp': {'community': 'public', 'version': '2c',
                     'device_profiles': 'grp_generic'}})
        r = client.post(self._url())
        assert r.status_code != 409, r.get_json()


class TestWhatTheFleetButtonRuns:
    """It is the DEVICES IN THE LIST, and that is narrower than "everything enabled".

    Written first as "every enabled module with anything to run", it swept up the modules that
    watch no device at all — a Microsoft 365 tenant, an Azure subscription — and the dialog
    opened on seventeen lines for a fleet of seventeen machines. Reported from the screen in
    those words: "I mean the devices in the infrastructure list".

    Asserted at the 409 boundary rather than on the returned list: what happens past it is the
    executor's, and this suite has no modules directory to run one from.
    """

    def _url(self):
        return '/api/v1/infra/collect'

    def _only(self, admin, monkeypatch, cfg):
        monkeypatch.setattr(admin, '_load_modules', lambda: cfg)

    def test_a_module_watching_no_device_is_not_the_fleet(self, admin, client, monkeypatch):
        """A cloud tenant is a check that runs and is not a machine on this screen. Collecting
        it because the button says "all" is the button doing more than it says."""
        _login(client)
        _mkhost(client, name='in-the-list', address='10.0.0.50')
        self._only(admin, monkeypatch, {
            'm365': {'enabled': True, 'list': {'tenant': {'enabled': True}}},
            'azure': {'enabled': True, 'list': {'sub': {'enabled': True, 'host_uid': ''}}},
        })
        r = client.post(self._url())
        assert r.status_code == 409, r.get_json()

    def test_an_item_bound_to_a_listed_device_is(self, admin, client, monkeypatch):
        _login(client)
        uid = _mkhost(client, name='in-the-list', address='10.0.0.51')
        self._only(admin, monkeypatch, {
            'ping': {'enabled': True, 'list': {'p': {'enabled': True, 'host_uid': uid}}}})
        assert client.post(self._url()).status_code != 409

    def test_a_cluster_check_counts_through_its_member_list(self, admin, client, monkeypatch):
        """The binding that is not `host_uid`. A keepalived VIP or a Proxmox cluster is ONE
        item bound to several machines through `host_uids` — the core's own convention, which
        host_binding, authz and the permission service all key on. Read only as `host_uid` it
        binds to nothing, so a module watching eight machines on this very screen was left out
        of the button that says it collects them. Caught against a real fleet, not by reading.
        """
        _login(client)
        uid = _mkhost(client, name='node-1', address='10.0.0.52')
        self._only(admin, monkeypatch, {
            'keepalived': {'enabled': True,
                           'list': {'vip': {'enabled': True, 'host_uids': [uid, 'gone']}}}})
        assert client.post(self._url()).status_code != 409

    def test_an_item_bound_to_a_machine_the_registry_no_longer_has_is_not(self, admin, client,
                                                                          monkeypatch):
        _login(client)
        _mkhost(client, name='in-the-list', address='10.0.0.53')
        self._only(admin, monkeypatch, {
            'ping': {'enabled': True,
                     'list': {'p': {'enabled': True, 'host_uid': 'deleted-long-ago'}}}})
        assert client.post(self._url()).status_code == 409

    def test_a_module_the_admin_switched_off_is_not_run(self, admin, client, monkeypatch):
        """"Collect" must not be a way to run something that was turned off."""
        _login(client)
        uid = _mkhost(client, name='in-the-list', address='10.0.0.54')
        self._only(admin, monkeypatch, {
            'ping': {'enabled': False, 'list': {'p': {'enabled': True, 'host_uid': uid}}}})
        assert client.post(self._url()).status_code == 409


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
