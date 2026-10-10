#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Access control in the physical inventory: turnstiles, readers and gateways (a Salto KS IQ), and
the lock a door or a locker carries (a Neo cylinder, an XS4 Locker) — which gateway it hangs from,
and its state, from its watched device or, in the demo, a demo state.
"""

import io
import os
import shutil
import tempfile

import pytest

from lib.core.dcim.store import ACCESS_KINDS, FEATURE_KINDS, LOCK_KINDS
from tests.conftest import _login
from tests.helpers import node_run, panel_bundle


def _site(client, name='S'):
    site = client.post('/api/v1/dcim/sites', json={'name': name}).get_json()['uid']
    room = client.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}).get_json()['uid']
    return site, room


def _feature(client, room, kind, **extra):
    r = client.post('/api/v1/dcim/features', json=dict({'room_uid': room, 'kind': kind}, **extra))
    return r


class TestTheModel:

    def test_turnstiles_and_readers_are_kinds_and_locks_are_closed(self):
        assert {'turnstile', 'reader'} <= set(FEATURE_KINDS)
        assert FEATURE_KINDS['reader']['base'] > 0             # it hangs on a wall
        assert set(LOCK_KINDS) == {'cylinder', 'escutcheon', 'locker', 'reader'}
        assert set(ACCESS_KINDS) == {'door', 'cabinet', 'turnstile', 'reader'}


class TestTheRoutes:

    def test_a_door_with_a_cylinder_hanging_from_a_gateway(self, admin, client):
        _login(client)
        _site_uid, room = _site(client)
        iq = _feature(client, room, 'reader', label='IQ P1', model='Salto IQ 3.0').get_json()['uid']
        door = _feature(client, room, 'door', lock='cylinder', model='Salto Neo', serial='N1',
                        hub_uid=iq).get_json()['uid']
        d = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()
        assert d['locks'] == list(LOCK_KINDS) and 'door' in d['access_kinds']
        assert [h['uid'] for h in d['hubs']] == [iq]
        lector = next(f for f in d['features'] if f['uid'] == iq)
        assert [g['uid'] for g in lector['hanging']] == [door]
        puerta = next(f for f in d['features'] if f['uid'] == door)
        assert puerta['lock'] == 'cylinder' and puerta['hub_uid'] == iq and puerta['state'] == ''

    def test_an_unknown_lock_or_a_gateway_that_is_not_a_reader_of_this_site(self, admin, client):
        _login(client)
        _s, room = _site(client)
        _s2, otra = _site(client, 'Otra')
        assert _feature(client, room, 'door', lock='candado').status_code == 400
        puerta = _feature(client, room, 'door').get_json()['uid']
        assert _feature(client, room, 'door', hub_uid=puerta).status_code == 400
        ajeno = _feature(client, otra, 'reader').get_json()['uid']
        assert _feature(client, room, 'door', hub_uid=ajeno).status_code == 400
        assert client.put(f'/api/v1/dcim/features/{puerta}',
                          json={'hub_uid': ajeno}).status_code == 400

    def test_a_piece_points_at_its_catalogue_model(self, admin, client):
        """Reported from the screen: the Salto models were text on the piece and nowhere in the
        catalogue. They are catalogue models now, of the access kinds, and the room offers each
        piece kind the models it can use."""
        _login(client)
        _s, room = _site(client)
        neo = admin._dcim_catalog.create({'manufacturer': 'Salto', 'model': 'Neo Cylinder',
                                          'kind': 'access_lock'}, 'manual')
        admin._dcim_catalog.create({'manufacturer': 'Salto', 'model': 'IQ 3.0',
                                    'kind': 'access_gateway'}, 'manual')
        door = _feature(client, room, 'door', lock='cylinder', type_uid=neo).get_json()['uid']
        assert _feature(client, room, 'door', type_uid='no-such-model').status_code == 400
        d = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()
        assert [m['name'] for m in d['access_types']['door']] == ['Salto Neo Cylinder']
        assert [m['name'] for m in d['access_types']['reader']] == ['Salto IQ 3.0']
        assert next(f for f in d['features'] if f['uid'] == door)['type_uid'] == neo

    def test_no_request_writes_a_demo_state(self, admin, client):
        """Only the demo writes it: through a request anybody could paint a real lock red."""
        _login(client)
        _s, room = _site(client)
        door = _feature(client, room, 'door', lock='cylinder', demo_state='error',
                        demo_reason='x').get_json()['uid']
        client.put(f'/api/v1/dcim/features/{door}', json={'demo_state': 'error', 'demo_reason': 'x'})
        f = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()['features'][0]
        assert f['demo_state'] == '' and f['state'] == '' and f['demo_reason'] == ''

    def test_a_demo_state_shows_and_a_watched_device_wins(self, admin, client):
        _login(client)
        _s, room = _site(client)
        door = _feature(client, room, 'door', lock='cylinder').get_json()['uid']
        admin._dcim_store.features.update(door, {'demo_state': 'warning'})
        f = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()['features'][0]
        assert f['state'] == 'warning'
        admin._dcim_store.features.update(door, {'device_uid': 'no-such-device'})
        f = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()['features'][0]
        assert f['state'] == ''                    # its device says nothing: no demo colour


_PROBE = r"""
__out = {};
_dcimMay = () => true;
_dcimDevices = [{uid: 'dev1', name: 'Salto KS'}];
_dcpFeat = {locks: ['cylinder', 'escutcheon', 'locker', 'reader'],
            access_kinds: ['door', 'cabinet', 'turnstile', 'reader'],
            access_types: {door: [{uid: 'neo', name: 'Salto Neo Cylinder', kind: 'access_lock'}]},
            hubs: [{uid: 'iq', label: 'IQ P1', room: 'NOC'}], features: [], kinds: {}};
const puerta = {uid: 'd', kind: 'door', lock: 'cylinder', model: 'Salto Neo', serial: 'N1',
                hub_uid: 'iq', state: 'warning', device_uid: '', type_uid: 'neo'};
const html = _dcpAccessHtml(puerta);
__out.puerta = [html.includes('Salto Neo'), html.includes('value="iq" selected'),
                html.includes('value="cylinder" selected'), html.includes('dev1'),
                html.includes('value="neo" selected')];
__out.columna = _dcpAccessHtml({uid: 'c', kind: 'column'});
const iq = _dcpAccessHtml({uid: 'iq', kind: 'reader', state: 'ok',
                           hanging: [{uid: 'd', kind: 'door', label: 'Puerta', room: 'CPD', state: 'warning'}]});
__out.iq = [iq.includes('CPD'), !iq.includes('value="iq"')];
__out.punto = [_dcpAccessDot(puerta, 10, 10).includes('<circle'),
               _dcpAccessDot({kind: 'door', lock: '', state: 'error'}, 10, 10),
               _dcpAccessDot({kind: 'door', lock: 'cylinder', state: ''}, 10, 10)];
"""


@pytest.fixture(scope='module')
def out():
    pytest.importorskip('flask')
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestTheInspector:

    def test_a_locks_fields_its_gateway_and_its_device(self, out):
        assert out['puerta'] == [True, True, True, True, True]
        assert out['columna'] == ''                # a column carries no access control

    def test_a_gateway_lists_what_hangs_from_it(self, out):
        assert out['iq'] == [True, True]           # and it cannot hang from itself

    def test_the_state_dot_only_on_what_carries_a_lock_and_has_a_state(self, out):
        assert out['punto'] == [True, '', '']
