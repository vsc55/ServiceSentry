#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deleting a rack that is not empty.

Reported: deleting a rack with things in it asked «delete?» and only then said it was not empty,
without saying what it held. Asked for: say it before asking, and offer to delete it with
everything. What is checked: what a site, a room or a rack holds can be asked before deleting;
a rack is still refused when not empty unless asked in so many words; asked, it goes with its
items, strips, cables, power leads and components, a power source that was one of its items
stays without one, what is around it in the room stays, it is audited — and a shared rack with
another company's item is not emptied by whoever may not delete that item.
"""

from __future__ import annotations

import pytest

from tests.conftest import _login                                   # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
    from tests.integration.test_wa_dcim import _as, fleet           # noqa: E402, F401
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def lleno(client):
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD'}))
    rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R04', 'u_height': 42}))
    srv = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 10, 'u_height': 2,
                                                  'label': 'SRV-1', 'role': 'server'}))
    pp = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 40, 'u_height': 1,
                                                 'label': 'PP-1', 'role': 'patch_panel'}))
    ups = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'SAI-R04', 'role': 'ups',
                                                  'placement': 'near'}))
    pdu = _uid(c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'PDU-A', 'feed': 'a',
                                                 'outlets': 8}))
    assert c.post('/api/v1/dcim/feeds', json={'item_uid': srv, 'pdu_uid': pdu, 'outlet': 1}).status_code == 200
    src = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': site, 'name': 'SAI R04', 'kind': 'ups',
                                                     'item_uid': ups}))
    roseta = _uid(c.post(f'/api/v1/dcim/rooms/{room}/items', json={'role': 'outlet', 'label': 'R-1'}))
    assert c.post('/api/v1/dcim/cables', json={'a_item': roseta, 'a_port': 'A-R', 'b_item': pp,
                                               'b_port': '1-R'}).status_code == 200
    puerta = _uid(c.post('/api/v1/dcim/features', json={'room_uid': room, 'kind': 'door'}))
    return dict(site=site, room=room, rack=rack, srv=srv, pp=pp, ups=ups, pdu=pdu, src=src,
                roseta=roseta, puerta=puerta)


class TestWhatItHolds:

    def test_asked_before_deleting(self, client, lleno):
        c = client
        assert c.get(f'/api/v1/dcim/racks/{lleno["rack"]}/holds').get_json() == {
            'contains': {'items': 3, 'pdus': 1}}
        assert c.get(f'/api/v1/dcim/rooms/{lleno["room"]}/holds').get_json() == {'contains': {'racks': 1}}
        assert c.get('/api/v1/dcim/racks/nope/holds').status_code == 404


class TestDeletingItWithEverything:

    def test_not_empty_is_still_refused_unless_asked(self, client, admin, lleno):
        r = client.delete(f'/api/v1/dcim/racks/{lleno["rack"]}')
        assert r.status_code == 409 and r.get_json()['contains'] == {'items': 3, 'pdus': 1}
        assert admin._dcim_store.racks.get(lleno['rack'])

    def test_asked_it_goes_with_what_it_holds_and_nothing_else(self, client, admin, lleno, monkeypatch):
        st = admin._dcim_store
        apuntado = []
        audit0 = admin._audit
        monkeypatch.setattr(admin, '_audit', lambda ev, **kw: (apuntado.append((ev, kw.get('detail'))), audit0(ev, **kw))[1])
        r = client.delete(f'/api/v1/dcim/racks/{lleno["rack"]}?contents=delete')
        assert r.status_code == 200, r.get_json()
        assert not st.racks.get(lleno['rack'])
        assert not any(st.items.get(lleno[k]) for k in ('srv', 'pp', 'ups'))
        assert not st.pdus.get(lleno['pdu']) and not st.feeds.list('item_uid = ?', (lleno['srv'],))
        assert not st.cables_of([lleno['roseta']]), 'the outlet keeps no cable to a panel that is gone'
        assert st.items.get(lleno['roseta']) and st.features.get(lleno['puerta']), 'what is around it stays'
        assert st.sources.get(lleno['src'])['item_uid'] == '', 'the source stays, saying no item'
        ev = [d for e, d in apuntado if e == 'dcim_rack_emptied']
        assert ev and ev[0]['items'] == 3 and ev[0]['pdus'] == 1 and ev[0]['cables'] == 1

    def test_another_companys_item_stops_it(self, admin, fleet):
        it_only = _as(admin, 'it-only', ['dcim_view', 'dcim_edit', f'org.{fleet["it"]}.view'])
        r = it_only.delete(f'/api/v1/dcim/racks/{fleet["rack"]}?contents=delete')
        assert r.status_code == 403 and r.get_json()['foreign'] == 1
        assert admin._dcim_store.items.get(fleet['mine']) and admin._dcim_store.items.get(fleet['theirs'])
