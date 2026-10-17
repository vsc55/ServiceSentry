#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A rack says which cabinet of the catalogue it is, and every road a rack travels keeps it.

`dc_rack.type_uid` links a rack to its model (tree `rack-types`). The API already refused
anything but a cabinet there; what was missing is everything around it: the rack's own answers
did not carry the model's NAME (the form and the header could only show a uid), the rack's
history did not record a change of model, a duplicated rack and a rack created by importing a
room plan came out of no model, and nothing could open one model's sheet by its uid.

And the room equipment: a PC, an IP phone, an AP, a camera, a display and a printer are classes
of the catalogue now (`catalog.KINDS`), with the plans' icons, so a model of one suggests its
role when it is placed.
"""

from __future__ import annotations

import pytest

from tests.conftest import _login                                   # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


@pytest.fixture()
def room(admin, client):
    """A logged-in client, a room, and two cabinets and a server in the catalogue."""
    _login(client)
    cat = admin._dcim_catalog                                       # noqa: SLF001
    gabinete = cat.create({'manufacturer': 'Acme', 'model': 'AR-42 600x1200',
                           'tree': 'rack-types', 'u_tenths': 420,
                           'extra': {'outer_width': 600, 'outer_depth': 1200,
                                     'mounting_depth': 1000, 'form_factor': '4-post-cabinet'}})
    pared = cat.create({'manufacturer': 'Acme', 'model': 'WM-12', 'tree': 'rack-types',
                        'u_tenths': 120, 'extra': {'form_factor': 'wall-cabinet'}})
    servidor = cat.create({'manufacturer': 'Acme', 'model': 'SRV-1', 'u_tenths': 10})
    sede = client.post('/api/v1/dcim/sites', json={'name': 'Sede A'}).get_json()['uid']
    sala = client.post('/api/v1/dcim/rooms',
                       json={'site_uid': sede, 'name': 'Sala 1'}).get_json()['uid']
    return {'room': sala, 'site': sede, 'cab': gabinete, 'wall': pared, 'srv': servidor}


def _rack(client, room, **extra):
    return client.post('/api/v1/dcim/racks',
                       json=dict({'room_uid': room['room'], 'name': 'R1'}, **extra)
                       ).get_json()['uid']


class TestTheRackSaysItsModelByName:

    def test_one_rack_and_the_room_list_carry_the_name(self, client, room):
        uid = _rack(client, room, type_uid=room['cab'])
        uno = client.get('/api/v1/dcim/racks/' + uid).get_json()['rack']
        assert uno['type_uid'] == room['cab'] and uno['type_name'] == 'Acme AR-42 600x1200'
        lista = client.get('/api/v1/dcim/racks?room=' + room['room']).get_json()['racks']
        assert [r['type_name'] for r in lista if r['uid'] == uid] == ['Acme AR-42 600x1200']

    def test_the_site_contents_carry_it_too(self, client, room):
        uid = _rack(client, room, type_uid=room['wall'])
        d = client.get('/api/v1/dcim/sites/%s/contents' % room['site']).get_json()
        racks = [r for sala in d.get('rooms', {}).values() for r in sala['racks']]
        assert [r['type_name'] for r in racks if r['uid'] == uid] == ['Acme WM-12']

    def test_a_rack_of_no_model_says_no_name(self, client, room):
        uid = _rack(client, room)
        uno = client.get('/api/v1/dcim/racks/' + uid).get_json()['rack']
        assert uno['type_uid'] == '' and 'type_name' not in uno

    def test_one_model_by_its_uid(self, client, room):
        d = client.get('/api/v1/dcim/catalog?tree=rack-types&uid=' + room['wall']).get_json()
        assert [t['uid'] for t in d['types']] == [room['wall']] and d['total'] == 1


class TestTheHistoryRecordsTheModel:

    def test_setting_changing_and_clearing_the_model_are_three_versions(self, admin, client,
                                                                        room):
        uid = _rack(client, room)
        client.put('/api/v1/dcim/racks/' + uid, json={'name': 'R1b'})   # a first version
        client.put('/api/v1/dcim/racks/' + uid, json={'type_uid': room['cab']})
        client.put('/api/v1/dcim/racks/' + uid, json={'type_uid': room['wall']})
        client.put('/api/v1/dcim/racks/' + uid, json={'type_uid': ''})
        d = client.get('/api/v1/dcim/racks/%s/history' % uid).get_json()
        cambios = [[c for c in f['changed'] if c['field'] == 'type_uid'] for f in d['history']]
        assert cambios[:3] == [
            [{'kind': 'rack', 'uid': '', 'label': '', 'field': 'type_uid',
              'from': room['wall'], 'to': ''}],
            [{'kind': 'rack', 'uid': '', 'label': '', 'field': 'type_uid',
              'from': room['cab'], 'to': room['wall']}],
            [{'kind': 'rack', 'uid': '', 'label': '', 'field': 'type_uid',
              'from': '', 'to': room['cab']}]]
        # …named, for the reader of the row.
        assert d['models'] == {room['cab']: 'Acme AR-42 600x1200', room['wall']: 'Acme WM-12'}

    def test_a_version_taken_before_the_model_was_kept_reads_as_none(self, admin, client, room):
        """An old snapshot has no `type_uid`: that is «no model», not a change — and setting the
        first model after it IS one, and is saved."""
        from lib.core.dcim import rackrev                           # noqa: PLC0415
        vieja = {'name': 'R', 'u_height': 42, 'items': []}
        assert rackrev.compare(vieja, dict(vieja, type_uid='')) == []
        assert rackrev.same(vieja, dict(vieja, type_uid=''))
        cambio = rackrev.compare(vieja, dict(vieja, type_uid='X'))
        assert [(c['field'], c['from'], c['to']) for c in cambio] == [('type_uid', '', 'X')]
        assert not rackrev.same(vieja, dict(vieja, type_uid='X'))

    def test_a_refused_model_writes_no_version(self, client, room):
        uid = _rack(client, room, type_uid=room['cab'])
        client.put('/api/v1/dcim/racks/' + uid, json={'name': 'R1c'})
        antes = len(client.get('/api/v1/dcim/racks/%s/history' % uid).get_json()['history'])
        client.put('/api/v1/dcim/racks/' + uid, json={'type_uid': room['srv']})
        d = client.get('/api/v1/dcim/racks/%s/history' % uid).get_json()
        assert len(d['history']) == antes
        assert client.get('/api/v1/dcim/racks/' + uid).get_json()['rack']['type_uid'] \
            == room['cab']


class TestAnImportedPlanKeepsTheModel:

    def test_a_new_rack_of_a_plan_keeps_its_cabinet_and_a_foreign_uid_is_lost(self, admin,
                                                                             client, room):
        r = client.post('/api/v1/dcim/rooms/%s/import' % room['room'], json={'racks': [
            {'name': 'P1', 'pos_x': 0, 'pos_y': 0, 'type_uid': room['cab']},
            {'name': 'P2', 'pos_x': 900, 'pos_y': 0, 'type_uid': room['srv']},
            {'name': 'P3', 'pos_x': 1800, 'pos_y': 0, 'type_uid': 'of-another-install'},
            {'name': 'P4', 'pos_x': 2700, 'pos_y': 0}]})
        d = r.get_json()
        assert r.status_code == 200 and d['racks_new'] == 4, d
        assert d['lost'].get('type_uid') == 2, d
        por_nombre = {k['name']: k for k in admin._dcim_store.racks_of(room['room'])}  # noqa
        assert por_nombre['P1']['type_uid'] == room['cab']
        assert [por_nombre[n]['type_uid'] for n in ('P2', 'P3', 'P4')] == ['', '', '']


class TestTheRoomEquipmentClasses:

    def test_the_catalogue_offers_them_with_the_plans_icons(self, client, room):
        from lib.core.dcim import catalog                           # noqa: PLC0415
        from lib.core.dcim.store import ITEM_ROLES                  # noqa: PLC0415
        d = client.get('/api/v1/dcim/catalog?tree=device-types').get_json()
        sala = ('pc', 'phone', 'ap', 'camera', 'display', 'printer')
        for k in sala:
            assert k in d['all_kinds'] and k in d['kinds_by_tree']['device-types'], k
            assert k in ITEM_ROLES and k in catalog.KINDS, k
        assert d['kind_icons'] == {'pc': 'bi-pc-display', 'phone': 'bi-telephone',
                                   'printer': 'bi-printer', 'ap': 'bi-wifi',
                                   'camera': 'bi-camera-video', 'display': 'bi-tv'}

    def test_a_model_of_one_keeps_it_and_suggests_its_role(self, admin, client, room):
        """Written with its class, a PC model stays a PC (before: «other», for not being in the
        vocabulary), and an item of it with no role says «the catalogue suggests: PC»."""
        r = client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'PC-9',
                                                      'tree': 'device-types', 'kind': 'pc',
                                                      'u_tenths': 10})
        tipo = r.get_json()['uid']
        assert admin._dcim_catalog.get(tipo)['kind'] == 'pc'        # noqa: SLF001
        rack = _rack(client, room)
        client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 1,
                                                'type_uid': tipo})
        items = client.get('/api/v1/dcim/racks/' + rack).get_json()['items']
        assert [i.get('role_hint') for i in items] == ['pc']
        # And correcting one to another class of the room is accepted.
        client.put('/api/v1/dcim/catalog/' + tipo, json={'kind': 'display'})
        assert admin._dcim_catalog.get(tipo)['kind'] == 'display'   # noqa: SLF001

    def test_a_fan_module_is_a_fan(self, admin, client):
        _login(client)
        r = client.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'FT-2',
                                                      'tree': 'module-types', 'kind': 'fan'})
        assert admin._dcim_catalog.get(r.get_json()['uid'])['kind'] == 'fan'   # noqa: SLF001
