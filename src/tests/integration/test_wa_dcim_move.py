#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moving: a server, a switch or a router to another rack —of the same room or another—, and a
rack to another room of its site.

Asked for. What is checked by the API: an item that changes rack takes what is mounted on it,
is unplugged from the old rack's power strips, keeps its data cables unless asked to disconnect
them, takes along a strip that IS it, and stops being the box of a power source of another
site; a U that is taken refuses it. A rack goes to another room of its site only, leaving its
row and its group and coming in at the corner. Both are audited. And in `node`, the panel's two
dialogs: the destinations offered and what they send.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def dos(client):
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    otra = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Respaldo'}))
    sala_a = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD-1'}))
    sala_b = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD-2'}))
    sala_x = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': otra, 'name': 'DR'}))
    ra = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': sala_a, 'name': 'RA', 'u_height': 42}))
    rb = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': sala_b, 'name': 'RB', 'u_height': 42}))
    rx = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': sala_x, 'name': 'RX', 'u_height': 42}))
    srv = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': ra, 'u_start': 10, 'u_height': 2,
                                                  'label': 'SRV-1', 'role': 'server'}))
    sw = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': ra, 'u_start': 40, 'u_height': 1,
                                                 'label': 'SW-1', 'role': 'switch'}))
    pdu = _uid(c.post('/api/v1/dcim/pdus', json={'rack_uid': ra, 'name': 'PDU-A', 'feed': 'a', 'outlets': 8}))
    assert c.post('/api/v1/dcim/feeds', json={'item_uid': srv, 'pdu_uid': pdu, 'outlet': 1}).status_code == 200
    assert c.post('/api/v1/dcim/cables', json={'a_item': srv, 'a_port': 'eth0', 'b_item': sw,
                                               'b_port': 'Gi1/0/1'}).status_code == 200
    ocupa = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rb, 'u_start': 20, 'u_height': 1,
                                                    'label': 'OCUPA', 'role': 'server'}))
    return dict(site=site, otra=otra, sala_a=sala_a, sala_b=sala_b, sala_x=sala_x, ra=ra, rb=rb, rx=rx,
                srv=srv, sw=sw, pdu=pdu, ocupa=ocupa)


class TestAnItemToAnotherRack:

    def test_it_goes_unplugged_with_its_cables_kept(self, client, admin, dos, monkeypatch):
        st = admin._dcim_store
        apuntado = []
        audit0 = admin._audit
        monkeypatch.setattr(admin, '_audit', lambda ev, **kw: (apuntado.append((ev, kw.get('detail'))), audit0(ev, **kw))[1])
        r = client.put(f'/api/v1/dcim/items/{dos["srv"]}', json={'rack_uid': dos['rb'], 'u_start': 5})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['moved'] == {'unplugged': 1, 'disconnected': 0, 'cables_kept': 1, 'sources_cleared': 0}
        it = st.items.get(dos['srv'])
        assert (it['rack_uid'], it['u_start']) == (dos['rb'], 5)
        assert not st.feeds.list('item_uid = ?', (dos['srv'],)), 'still plugged into the old rack'
        assert len(st.cables_of([dos['srv']])) == 1
        ev = [d for e, d in apuntado if e == 'dcim_moved']
        assert ev and ev[0]['rack_from'] == dos['ra'] and ev[0]['rack_to'] == dos['rb']

    def test_asked_its_data_cables_are_disconnected(self, client, admin, dos):
        r = client.put(f'/api/v1/dcim/items/{dos["srv"]}', json={'rack_uid': dos['rb'], 'u_start': 5,
                                                                  'disconnect': True})
        assert r.status_code == 200 and r.get_json()['moved']['disconnected'] == 1
        assert not admin._dcim_store.cables_of([dos['srv']])

    def test_a_taken_u_refuses_it_and_nothing_changes(self, client, admin, dos):
        r = client.put(f'/api/v1/dcim/items/{dos["srv"]}', json={'rack_uid': dos['rb'], 'u_start': 20})
        assert r.status_code == 400
        st = admin._dcim_store
        assert st.items.get(dos['srv'])['rack_uid'] == dos['ra'] and st.feeds.list('item_uid = ?', (dos['srv'],))

    def test_a_strip_that_is_the_item_goes_with_it(self, client, admin, dos):
        st = admin._dcim_store
        regleta = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': dos['ra'], 'label': 'PDU-B',
                                                               'role': 'pdu', 'placement': 'side'}))
        st.pdus.update(dos['pdu'], {'item_uid': regleta}, actor='t')
        r = client.put(f'/api/v1/dcim/items/{regleta}', json={'rack_uid': dos['rb']})
        assert r.status_code == 200, r.get_json()
        assert st.pdus.get(dos['pdu'])['rack_uid'] == dos['rb']
        assert not st.feeds_of([dos['pdu']]), 'the old rack is no longer plugged into it'

    def test_a_ups_to_another_site_is_no_longer_its_sources_box(self, client, admin, dos):
        st = admin._dcim_store
        sai = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': dos['ra'], 'label': 'SAI',
                                                           'role': 'ups', 'placement': 'near'}))
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['site'], 'name': 'SAI RA',
                                                             'kind': 'ups', 'item_uid': sai}))
        assert client.put(f'/api/v1/dcim/items/{sai}', json={'rack_uid': dos['rb']}).status_code == 200
        assert st.sources.get(src)['item_uid'] == sai, 'same site: still its box'
        r = client.put(f'/api/v1/dcim/items/{sai}', json={'rack_uid': dos['rx']})
        assert r.status_code == 200 and r.get_json()['moved']['sources_cleared'] == 1
        assert st.sources.get(src)['item_uid'] == ''


class TestARackToAnotherRoom:

    def test_of_its_site_leaving_its_row_and_group(self, client, admin, dos, monkeypatch):
        st = admin._dcim_store
        fila = _uid(client.post('/api/v1/dcim/rows', json={'room_uid': dos['sala_a'], 'name': 'Fila 1'}))
        st.racks.update(dos['ra'], {'row_uid': fila, 'group_uid': 'g-abc', 'pos_x': 3000, 'pos_y': 2000}, actor='t')
        apuntado = []
        audit0 = admin._audit
        monkeypatch.setattr(admin, '_audit', lambda ev, **kw: (apuntado.append(ev), audit0(ev, **kw))[1])
        r = client.put(f'/api/v1/dcim/racks/{dos["ra"]}', json={'room_uid': dos['sala_b']})
        assert r.status_code == 200, r.get_json()
        k = st.racks.get(dos['ra'])
        assert (k['room_uid'], k['row_uid'], k['group_uid'], k['pos_x'], k['pos_y']) == (dos['sala_b'], '', '', 0, 0)
        assert st.items.get(dos['srv'])['rack_uid'] == dos['ra'], 'what it holds goes with it'
        assert 'dcim_moved' in apuntado

    def test_not_to_another_site(self, client, admin, dos):
        r = client.put(f'/api/v1/dcim/racks/{dos["ra"]}', json={'room_uid': dos['sala_x']})
        assert r.status_code == 400
        assert admin._dcim_store.racks.get(dos['ra'])['room_uid'] == dos['sala_a']


_PROBE = r"""
__out = {};
// What the panel really holds: the answer of /api/v1/dcim/sites (`racks` there is a count, the
// list is `rackList`). Reported by a bug hunt: the dialogs read `racks` and broke on real data,
// while this test built the data by hand in a shape the server never sends.
_dcimData = __SITES__;
const nombre = (uid) => { for (const s of _dcimData.sites) for (const r of s.rooms || [])
    for (const k of r.rackList || []) if (k.uid === uid) return k.name; return ''; };
const ra = Object.values(__UIDS__).find(u => nombre(u) === 'RA');
__out.grupos = _dcMoveRackGroups(ra).map(g => [g.label, g.racks.map(k => k.name)]);
let modal = '';
showHtmlModal = (titulo, html, v, acciones) => { modal = html + acciones; };
_dcMoveRack(ra);
__out.salas = (modal.match(/<option value="([^"]+)">([^<]+)</g) || []).map(x => x.split('>')[1].split('<')[0]);
"""


@pytest.fixture(scope='module')
def out():
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
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    uids = {}
    for sala, racks in (('CPD-1', ('RA', 'RA2')), ('CPD-2', ('RB',)), ('Vacia', ())):
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': sala}))
        for k in racks:
            uids[k] = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': k, 'u_height': 42}))
    import json                                                     # noqa: PLC0415
    sitios = json.dumps(c.get('/api/v1/dcim/sites').get_json())
    return node_run(panel_bundle(c), _PROBE.replace('__SITES__', sitios).replace('__UIDS__', json.dumps(uids)))


class TestTheDialogs:

    def test_an_item_is_offered_every_other_rack_by_site_and_room(self, out):
        assert out['grupos'] == [['Sede › CPD-1', ['RA2']], ['Sede › CPD-2', ['RB']]]

    def test_a_rack_is_offered_the_other_rooms_of_its_site(self, out):
        assert out['salas'] == ['CPD-2', 'Vacia']
