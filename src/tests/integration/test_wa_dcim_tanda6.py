#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DCIM holes of the second 2026-10-12 audit (DC-1 … DC-14) — each pinned so it does not come back.

The scenario of most of them: a user of company A, and things of company B inside A's site, room
or rack. Routes that list items to READ them reused the elevation's filter, whose opaque rows
carry a uid: cables between B's boxes, a 500 on B's socket, B's room items drawn at (0, 0). A
shared rack's owner cabled and plugged B's boxes. A room's features listed B's racks and readers.
A plan import moved B's rack by name, and re-importing an exported plan lost its access control
and unlinked its sources and doors. And a handful of loose ends: a mount on a room item, gateways
left dangling, a floor's area moved away, a device place with no room, structured values in text
columns, a row of another room, unbounded import measures, a search that named B's labels.
"""

from __future__ import annotations

import json
import shutil

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_A_PERMS = ['dcim_view', 'dcim_edit', 'dcim_cable_edit']


def _uid(r):
    assert r.status_code in (200, 201), (r.status_code, r.get_json())
    return r.get_json()['uid']


@pytest.fixture()
def mix(admin, client):
    """A's site, room and two racks; B's boxes in both racks, cabled together; B's room items in
    A's room; a user of A and a user of B."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': s, 'org_uid': a})
    r1 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R1'}))
    k1 = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r1, 'name': 'K1', 'u_height': 42}))
    k2 = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r1, 'name': 'K2', 'u_height': 42}))
    b1 = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k1, 'u_start': 1, 'u_height': 1,
                                                 'label': 'B-SECRET-1'}))
    b2 = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k2, 'u_start': 1, 'u_height': 1,
                                                 'label': 'B-SECRET-2'}))
    mine = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k1, 'u_start': 10, 'u_height': 1,
                                                   'label': 'A-SW'}))
    for it in (b1, b2):
        assert c.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': it,
                                                  'org_uid': b}).status_code == 200
    cable = _uid(c.post('/api/v1/dcim/cables', json={
        'a_item': b1, 'b_item': b2, 'a_port': 'B-PORT-X', 'b_port': 'B-PORT-Y',
        'label': 'B-CABLE-LABEL'}))
    ua = _login_as(admin, 'ua', perms=_A_PERMS + [f'org.{a}.view'])
    ub = _login_as(admin, 'ub', perms=_A_PERMS + [f'org.{b}.view'])
    return dict(a=a, b=b, s=s, r1=r1, k1=k1, k2=k2, b1=b1, b2=b2, mine=mine, cable=cable,
                ua=ua, ub=ub)


def _room_item(client, room, owner=None, **body):
    uid = _uid(client.post(f'/api/v1/dcim/rooms/{room}/items', json=body))
    if owner:
        assert client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': uid,
                                                       'org_uid': owner}).status_code == 200
    return uid


class TestReadersOnlyGetWhatTheyMayRead:
    """DC-1, DC-2, DC-3 — routes that list items to read them skip somebody else's."""

    def test_site_circuits_do_not_carry_a_cable_between_two_foreign_boxes(self, client, mix):
        r = mix['ua'].get(f'/api/v1/dcim/sites/{mix["s"]}/circuits')
        assert r.status_code == 200
        texto = json.dumps(r.get_json())
        for secreto in ('B-CABLE-LABEL', 'B-PORT-X', 'B-PORT-Y', mix['cable']):
            assert secreto not in texto, secreto

    def test_site_circuits_hnet_does_not_carry_a_foreign_room_item_cable(self, client, mix):
        pc = _room_item(client, mix['r1'], mix['b'], role='pc', label='B-PC')
        assert client.post('/api/v1/dcim/cables', json={
            'a_item': pc, 'b_item': mix['b1'], 'a_port': 'B-NIC', 'b_port': 'eth9',
            'label': 'B-HORIZONTAL'}).status_code == 200
        d = mix['ua'].get(f'/api/v1/dcim/sites/{mix["s"]}/circuits').get_json()
        assert d['hnet'] == []
        assert 'B-HORIZONTAL' not in json.dumps(d) and 'B-NIC' not in json.dumps(d)

    def test_a_foreign_socket_does_not_break_the_sources_of_a_scoped_reader(self, client, mix):
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': mix['s'], 'name': 'UPS',
                                                            'kind': 'ups'}))
        _room_item(client, mix['r1'], mix['b'], role='power_outlet', label='B-SOCK',
                   source_uid=src)
        r = mix['ua'].get('/api/v1/dcim/sources')
        assert r.status_code == 200
        assert 'B-SOCK' not in json.dumps(r.get_json()['sockets'])

    def test_foreign_room_items_are_not_listed_without_geometry(self, client, mix):
        pc = _room_item(client, mix['r1'], mix['b'], role='pc', label='B-PC')
        own = _room_item(client, mix['r1'], None, role='outlet', label='A-OUT')
        for url in (f'/api/v1/dcim/rooms/{mix["r1"]}/items',
                    f'/api/v1/dcim/rooms/{mix["r1"]}/features'):
            items = mix['ua'].get(url).get_json()['items']
            uids = [i['uid'] for i in items]
            assert pc not in uids and own in uids, url
            assert not any(i.get('foreign') for i in items), url


class TestCablesAnswerToTheirBoxes:
    """DC-4 — a shared rack's owner does not cable, re-cable or plug another company's boxes,
    and that company can cable its own."""

    def test_the_rack_owner_may_not_cable_two_foreign_boxes(self, client, mix):
        r = mix['ua'].post('/api/v1/dcim/cables', json={'a_item': mix['b1'], 'b_item': mix['b2'],
                                                        'a_port': 'p9', 'b_port': 'p9'})
        assert r.status_code == 403

    def test_the_rack_owner_may_not_edit_or_delete_their_cable(self, admin, client, mix):
        r = mix['ua'].put(f'/api/v1/dcim/cables/{mix["cable"]}', json={'label': 'A-RENAMED'})
        assert r.status_code == 403
        assert mix['ua'].delete(f'/api/v1/dcim/cables/{mix["cable"]}').status_code == 403
        fila = admin._dcim_store.cables.get(mix['cable'])
        assert fila and fila['label'] == 'B-CABLE-LABEL'

    def test_the_rack_owner_may_not_plug_or_unplug_a_foreign_box(self, admin, client, mix):
        pdu = _uid(mix['ua'].post('/api/v1/dcim/pdus', json={'rack_uid': mix['k1'], 'name': 'P',
                                                             'outlets': 8}))
        r = mix['ua'].post('/api/v1/dcim/feeds', json={'pdu_uid': pdu, 'item_uid': mix['b1'],
                                                       'outlet': 1})
        assert r.status_code == 403
        feed = _uid(client.post('/api/v1/dcim/feeds', json={'pdu_uid': pdu, 'item_uid': mix['b1'],
                                                            'outlet': 2}))
        assert mix['ua'].put(f'/api/v1/dcim/feeds/{feed}', json={'outlet': 3}).status_code == 403
        assert mix['ua'].delete(f'/api/v1/dcim/feeds/{feed}').status_code == 403
        assert admin._dcim_store.feeds.get(feed)

    def test_the_box_owner_cables_its_own_boxes_in_somebody_elses_rack(self, admin, client, mix):
        r = mix['ub'].post('/api/v1/dcim/cables', json={'a_item': mix['b1'], 'b_item': mix['b2'],
                                                        'a_port': 'eth1', 'b_port': 'eth1'})
        assert r.status_code == 200, r.get_json()
        nuevo = r.get_json()['uid']
        assert mix['ub'].put(f'/api/v1/dcim/cables/{nuevo}', json={'label': 'B2'}).status_code == 200
        assert mix['ub'].delete(f'/api/v1/dcim/cables/{nuevo}').status_code == 200
        # …and still not to the rack owner's switch: that end is A's.
        r = mix['ub'].post('/api/v1/dcim/cables', json={'a_item': mix['b1'], 'b_item': mix['mine'],
                                                        'a_port': 'eth2', 'b_port': 'g1'})
        assert r.status_code == 403


@pytest.fixture()
def bajo(admin, client):
    """A's site with A's room RA, B's room RB in it, and B's rack in RA."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': s, 'org_uid': a})
    ra = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'RA'}))
    rb = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'B-SECRET-ROOM'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'room', 'uid': rb, 'org_uid': b})
    kb = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': ra, 'name': 'B-SECRET-RACK',
                                                 'u_height': 42, 'description': 'B-RACK-DESC',
                                                 'pos_x': 1000}))
    c.post('/api/v1/orgs/owner', json={'scope': 'rack', 'uid': kb, 'org_uid': b})
    rd = _uid(c.post('/api/v1/dcim/features', json={'room_uid': rb, 'kind': 'reader',
                                                    'label': 'B-READER'}))
    _uid(c.post('/api/v1/dcim/features', json={'room_uid': rb, 'kind': 'door',
                                               'label': 'B-DOOR', 'hub_uid': rd}))
    ua = _login_as(admin, 'ua', perms=_A_PERMS + [f'org.{a}.view'])
    return dict(a=a, b=b, s=s, ra=ra, rb=rb, kb=kb, rd=rd, ua=ua)


class TestARoomSaysOnlyWhatTheReaderMaySee:

    def test_rows_and_loose_racks_leave_out_a_foreign_rack(self, bajo):
        """DC-5 — `loose` returned the room's every rack, whole."""
        d = bajo['ua'].get(f'/api/v1/dcim/rooms/{bajo["ra"]}/features').get_json()
        texto = json.dumps({k: d.get(k) for k in ('rows', 'loose')})
        assert 'B-SECRET-RACK' not in texto and 'B-RACK-DESC' not in texto and bajo['kb'] not in texto

    def test_gateways_of_a_room_the_reader_cannot_see_are_not_offered(self, bajo):
        """DC-6 — the hubs of the site came with their label and their room's name."""
        d = bajo['ua'].get(f'/api/v1/dcim/rooms/{bajo["ra"]}/features').get_json()
        texto = json.dumps(d.get('hubs'))
        assert 'B-READER' not in texto and 'B-SECRET-ROOM' not in texto and bajo['rd'] not in texto

    def test_import_does_not_move_a_foreign_rack_nor_tell_its_name(self, admin, bajo):
        """DC-7 — matched by name among all racks, the file moved B's rack, and «moved» against
        «new» told which names the room hides."""
        r = bajo['ua'].post(f'/api/v1/dcim/rooms/{bajo["ra"]}/import', json={
            'features': [], 'racks': [{'name': 'B-SECRET-RACK', 'pos_x': 7777, 'pos_y': 1}]})
        assert r.status_code == 200
        d = r.get_json()
        assert d['racks_moved'] == 0 and d['racks_new'] == 1
        assert admin._dcim_store.racks.get(bajo['kb'])['pos_x'] == 1000


def _export(client, room):
    """The plan file the panel writes (`_dcPlanFeatureOut` / `_dcPlanRackOut`), built from the
    same answer the panel builds it from."""
    d = client.get(f'/api/v1/dcim/rooms/{room}/features').get_json()
    campos = ('kind', 'label', 'pos_x', 'pos_y', 'width_mm', 'depth_mm', 'rotation', 'height_mm',
              'base_mm', 'shelves', 'lock', 'type_uid', 'model', 'serial', 'hub_uid',
              'device_uid', 'group_uid')
    return {'features': [dict({k: f.get(k) for k in campos}, ref=f['uid'])
                         for f in d['features']], 'racks': []}


class TestAPlanComesBackWhole:
    """DC-8 — re-importing the exported plan kept nothing but the geometry."""

    @pytest.fixture()
    def sala(self, client):
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        r1 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R1'}))
        rd = _uid(c.post('/api/v1/dcim/features', json={
            'room_uid': r1, 'kind': 'reader', 'label': 'RD', 'device_uid': 'dev-9',
            'serial': 'SN-RD', 'model': 'IQ'}))
        door = _uid(c.post('/api/v1/dcim/features', json={
            'room_uid': r1, 'kind': 'door', 'label': 'D', 'hub_uid': rd, 'lock': 'cylinder',
            'group_uid': 'g-ab'}))
        pan = _uid(c.post('/api/v1/dcim/features', json={'room_uid': r1, 'kind': 'panel',
                                                         'label': 'PANEL'}))
        src = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': s, 'name': 'P',
                                                        'kind': 'panel'}))
        assert c.put(f'/api/v1/dcim/sources/{src}', json={'feature_uid': pan}).status_code == 200
        return dict(s=s, r1=r1, rd=rd, door=door, pan=pan, src=src)

    def test_reimporting_the_export_keeps_uids_links_and_access_control(self, admin, client, sala):
        doc = _export(client, sala['r1'])
        r = client.post(f'/api/v1/dcim/rooms/{sala["r1"]}/import', json=doc)
        assert r.status_code == 200 and r.get_json()['lost'] == {}
        st = admin._dcim_store
        door = st.features.get(sala['door'])
        assert door and door['hub_uid'] == sala['rd']
        assert door['lock'] == 'cylinder' and door['group_uid'] == 'g-ab'
        rd = st.features.get(sala['rd'])
        assert rd['device_uid'] == 'dev-9' and rd['serial'] == 'SN-RD' and rd['model'] == 'IQ'
        assert st.sources.get(sala['src'])['feature_uid'] == sala['pan']

    def test_into_another_room_the_door_follows_its_reader_of_the_file(self, admin, client, sala):
        doc = _export(client, sala['r1'])
        r2 = _uid(client.post('/api/v1/dcim/rooms', json={'site_uid': sala['s'], 'name': 'R2'}))
        r = client.post(f'/api/v1/dcim/rooms/{r2}/import', json=doc)
        assert r.status_code == 200
        nuevas = {f['label']: f for f in admin._dcim_store.features_of(r2)}
        assert nuevas['D']['hub_uid'] == nuevas['RD']['uid'] != sala['rd']
        assert nuevas['D']['lock'] == 'cylinder'

    def test_what_cannot_come_back_is_counted_not_dropped_in_silence(self, admin, client, sala):
        doc = _export(client, sala['r1'])
        for f in doc['features']:
            if f['label'] == 'D':
                f['hub_uid'] = 'no-such-reader'
            if f['label'] == 'RD':
                f['type_uid'] = 'no-such-model'
        r = client.post(f'/api/v1/dcim/rooms/{sala["r1"]}/import', json=doc)
        assert r.get_json()['lost'] == {'hub_uid': 1, 'type_uid': 1}
        assert admin._dcim_store.features.get(sala['door'])['hub_uid'] == ''

    def test_the_panel_writes_the_fields_into_the_file(self, client):
        """The client half: `_dcPlanFeatureOut` carries what the server now reads back."""
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        from tests.helpers import node_run, panel_bundle                # noqa: PLC0415
        _login(client)
        probe = ("__out = {}; __out.f = _dcPlanFeatureOut({uid: 'u1', kind: 'door', label: 'D', "
                 "lock: 'cylinder', type_uid: 't', model: 'm', serial: 's', hub_uid: 'h', "
                 "device_uid: 'd', group_uid: 'g'});"
                 "__out.r = _dcPlanRackOut({name: 'K', group_uid: 'g2'});")
        out = node_run(panel_bundle(client), probe)
        assert out['f'] == dict(out['f'], ref='u1', lock='cylinder', type_uid='t', model='m',
                                serial='s', hub_uid='h', device_uid='d', group_uid='g')
        assert out['r']['group_uid'] == 'g2'


class TestLooseEnds:

    def test_nothing_mounts_on_a_room_item(self, admin, client):
        """DC-9 — mounted on a desk PC, a server took no rack, no room and no owner."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        r = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R'}))
        k = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r, 'name': 'K', 'u_height': 42}))
        srv = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k, 'u_start': 5, 'u_height': 2,
                                                      'label': 'SRV'}))
        pc = _room_item(c, r, None, role='pc', label='PC')
        resp = c.put(f'/api/v1/dcim/items/{srv}', json={'parent_uid': pc})
        assert resp.status_code == 400
        fila = admin._dcim_store.items.get(srv)
        assert fila['rack_uid'] == k and not fila.get('parent_uid')
        resp = c.post('/api/v1/dcim/items', json={'parent_uid': pc, 'label': 'ORPHAN'})
        assert resp.status_code == 400
        assert not admin._dcim_store.children_of(pc)

    def test_a_door_lets_go_of_a_reader_deleted_rekinded_or_moved_away(self, admin, client):
        """DC-10 — the doors kept naming a gateway that was gone or no gateway at all."""
        _login(client)
        c = client
        st = admin._dcim_store
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        s2 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S2'}))
        r1 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R1'}))
        r2 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R2'}))

        def puerta(hub):
            return _uid(c.post('/api/v1/dcim/features', json={'room_uid': r1, 'kind': 'door',
                                                              'label': 'D', 'hub_uid': hub}))

        def lector(room):
            return _uid(c.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': 'reader',
                                                              'label': 'RD'}))
        # Deleted.
        rd = lector(r1)
        d = puerta(rd)
        assert c.delete(f'/api/v1/dcim/features/{rd}').status_code == 200
        assert st.features.get(d)['hub_uid'] == ''
        # No longer a reader.
        rd = lector(r1)
        d = puerta(rd)
        assert c.put(f'/api/v1/dcim/features/{rd}', json={'kind': 'column'}).status_code == 200
        assert st.features.get(d)['hub_uid'] == ''
        # Its room deleted (the door is in another room of the site).
        rd = lector(r2)
        d = puerta(rd)
        assert c.delete(f'/api/v1/dcim/rooms/{r2}').status_code == 200
        assert st.features.get(d)['hub_uid'] == ''
        # Its room moved to another site.
        r3 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R3'}))
        rd = lector(r3)
        d = puerta(rd)
        assert c.put(f'/api/v1/dcim/rooms/{r3}', json={'site_uid': s2}).status_code == 200
        assert st.features.get(d)['hub_uid'] == ''

    def test_a_floor_general_area_stays_in_its_site(self, admin, client):
        """DC-11."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        s2 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S2'}))
        fl = _uid(c.post('/api/v1/dcim/floors', json={'site_uid': s, 'name': 'F'}))
        area = c.post(f'/api/v1/dcim/floors/{fl}/area').get_json()['room_uid']
        assert c.put(f'/api/v1/dcim/rooms/{area}', json={'site_uid': s2}).status_code == 400
        assert admin._dcim_store.rooms.get(area)['site_uid'] == s

    def test_a_device_on_a_desk_has_a_place(self, client):
        """DC-12 — a room item's place was read through its rack, and it has none."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SEDE-1'}))
        r = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'OFICINA-1'}))
        _room_item(c, r, None, role='pc', label='PC', device_uid='dev-1')
        lugares = c.get('/api/v1/dcim/devices/dev-1/place').get_json()['places']
        assert len(lugares) == 1
        assert lugares[0]['room']['name'] == 'OFICINA-1' and lugares[0]['site']['name'] == 'SEDE-1'

    def test_a_list_or_an_object_in_a_text_column_is_a_400(self, admin, client):
        """DC-13 — a structured value in a TEXT column reached the driver: a 500."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        r = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R'}))
        k = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r, 'name': 'K', 'u_height': 42}))
        it = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k, 'u_start': 1, 'label': 'I'}))
        row = _uid(c.post('/api/v1/dcim/rows', json={'room_uid': r, 'name': 'A'}))
        admin.app.config['PROPAGATE_EXCEPTIONS'] = False
        try:
            for metodo, url, body in (
                    ('put', f'/api/v1/dcim/racks/{k}', {'name': {'a': 1}}),
                    ('post', '/api/v1/dcim/racks', {'room_uid': r, 'name': ['x']}),
                    ('post', '/api/v1/dcim/rows', {'room_uid': r, 'name': [1]}),
                    ('put', f'/api/v1/dcim/rows/{row}', {'front_aisle': [1]}),
                    ('post', f'/api/v1/dcim/rooms/{r}/items', {'role': 'pc', 'label': [1]}),
                    ('post', '/api/v1/dcim/sources', {'site_uid': s, 'name': [1]}),
                    ('put', f'/api/v1/dcim/items/{it}', {'label': {'x': 1}}),
                    ('post', '/api/v1/dcim/features', {'room_uid': r, 'kind': 'column',
                                                       'label': [1]})):
                resp = getattr(c, metodo)(url, json=body)
                assert resp.status_code == 400, (url, body, resp.status_code)
        finally:
            admin.app.config['PROPAGATE_EXCEPTIONS'] = None

    def test_a_rack_row_is_one_of_its_room(self, admin, client):
        """DC-13 — `row_uid` took a row of another room, of another site."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        s2 = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S2'}))
        r1 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R1'}))
        r2 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s2, 'name': 'R2'}))
        ajena = _uid(c.post('/api/v1/dcim/rows', json={'room_uid': r2, 'name': 'ROW2'}))
        suya = _uid(c.post('/api/v1/dcim/rows', json={'room_uid': r1, 'name': 'ROW1'}))
        k = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r1, 'name': 'K', 'u_height': 42}))
        assert c.put(f'/api/v1/dcim/racks/{k}', json={'row_uid': ajena}).status_code == 400
        assert c.post('/api/v1/dcim/racks', json={'room_uid': r1, 'name': 'K2', 'u_height': 42,
                                                  'row_uid': ajena}).status_code == 400
        assert c.put(f'/api/v1/dcim/racks/{k}', json={'row_uid': suya}).status_code == 200
        assert admin._dcim_store.racks.get(k)['row_uid'] == suya

    def test_import_measures_are_bounded(self, admin, client):
        """DC-13 — thirty nines and `1e300` went to the engine as they came."""
        _login(client)
        c = client
        s = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        r = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': s, 'name': 'R'}))
        resp = c.post(f'/api/v1/dcim/rooms/{r}/import', json={
            'room': {'width_mm': '9' * 30},
            'racks': [{'name': 'NEW', 'width_mm': 1e300, 'pos_x': -1e300}],
            'features': [{'kind': 'column', 'label': 'C', 'width_mm': 1e300, 'pos_y': 1e300}]})
        assert resp.status_code == 200, resp.get_json()
        st = admin._dcim_store
        assert int(st.rooms.get(r)['width_mm']) <= 10 ** 9
        rack = st.racks_of(r)[0]
        assert int(rack['width_mm']) <= 10 ** 9 and float(rack['pos_x']) >= -10 ** 9
        col = st.features_of(r)[0]
        assert int(col['width_mm']) <= 10 ** 9 and float(col['pos_y']) <= 10 ** 9

    def test_a_cable_search_does_not_match_a_foreign_label(self, client, mix):
        """DC-14 — a cable of one's own switch to B's box came back for B's label."""
        assert client.post('/api/v1/dcim/cables', json={
            'a_item': mix['mine'], 'b_item': mix['b2'], 'a_port': 'g1',
            'b_port': 'eth0'}).status_code == 200
        hits = {q: len(mix['ua'].get('/api/v1/dcim/cables', query_string={'q': q})
                       .get_json()['cables'])
                for q in ('B-SECRET-2', 'B-SECRET-9', 'K2')}
        assert hits['B-SECRET-2'] == hits['B-SECRET-9'] == 0
        # Its own label, and the name of its own rack, still find it.
        assert hits['K2'] == 1
        assert len(mix['ua'].get('/api/v1/dcim/cables', query_string={'q': 'A-SW'})
                   .get_json()['cables']) == 1

    def test_a_cable_search_does_not_match_a_foreign_rack_name(self, admin, client, mix):
        """DC-14 — the rack-name half of the same oracle: one's own switch cabled to a box in
        another company's rack, found by the name of that rack — which this reader cannot list."""
        rb = _uid(client.post('/api/v1/dcim/racks', json={'room_uid': mix['r1'],
                                                          'name': 'B-HIDDEN-RACK', 'u_height': 42}))
        client.post('/api/v1/orgs/owner', json={'scope': 'rack', 'uid': rb, 'org_uid': mix['b']})
        suyo = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': rb, 'u_start': 1,
                                                            'label': 'B-BOX'}))
        assert client.post('/api/v1/dcim/cables', json={
            'a_item': mix['mine'], 'b_item': suyo, 'a_port': 'g2', 'b_port': 'eth0'}
        ).status_code == 200
        for q in ('B-HIDDEN-RACK', 'B-NOTHING-RACK'):
            assert mix['ua'].get('/api/v1/dcim/cables',
                                 query_string={'q': q}).get_json()['cables'] == [], q
