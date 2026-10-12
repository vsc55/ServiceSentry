#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DCIM server holes of the 2026-10-12 audit, fourth batch — each pinned so it does not come back.

Rack items and their parts stored numbers unchecked (`depth_mm: "abc"` broke the rack view for
good) and roles unchecked when mounted or edited; mounting on somebody else's tray was not a
write to it; deleting an item or a plan piece, or importing a plan, left power sources and
strips naming what was gone; room items skipped asset numbering; a room moved to another site
kept its strips on the old site's sources; a source could hang off another company's source,
and cloning one copied rows into sites the caller cannot write; a template's files were behind
the catalogue's permissions instead of the template's.
"""

from __future__ import annotations

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


def _uid(r):
    assert r.status_code in (200, 201), r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def dos(admin, client):
    """Two companies, each with a site, a room and a rack; an item in each rack; and a user of A."""
    _login(client)
    c = client
    a = _uid(c.post('/api/v1/orgs', json={'name': 'A', 'short': 'A'}))
    b = _uid(c.post('/api/v1/orgs', json={'name': 'B', 'short': 'B'}))
    sa = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SA'}))
    sb = _uid(c.post('/api/v1/dcim/sites', json={'name': 'SB'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sa, 'org_uid': a})
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': sb, 'org_uid': b})
    ra = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': sa, 'name': 'RA'}))
    rb = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': sb, 'name': 'RB'}))
    ka = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': ra, 'name': 'KA', 'u_height': 42}))
    kb = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': rb, 'name': 'KB', 'u_height': 42}))
    ia = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': ka, 'u_start': 1, 'u_height': 1,
                                                 'label': 'IA'}))
    ua = _login_as(admin, 'ua', perms=['dcim_view', 'dcim_edit', f'org.{a}.view'])
    return dict(a=a, b=b, sa=sa, sb=sb, ra=ra, rb=rb, ka=ka, kb=kb, ia=ia, ua=ua)


class TestItemNumbers:
    """D6 — a rack item's numbers and role, checked at the door."""

    def test_a_text_depth_is_refused_on_create_and_edit(self, admin, client, dos):
        r = client.post('/api/v1/dcim/items', json={'rack_uid': dos['ka'], 'u_start': 5,
                                                    'depth_mm': 'abc'})
        assert r.status_code == 400 and r.get_json().get('field') == 'depth_mm'
        r = client.put(f'/api/v1/dcim/items/{dos["ia"]}', json={'depth_mm': 'abc'})
        assert r.status_code == 400
        assert client.get(f'/api/v1/dcim/racks/{dos["ka"]}').status_code == 200

    def test_a_negative_depth_is_refused(self, admin, client, dos):
        r = client.put(f'/api/v1/dcim/items/{dos["ia"]}', json={'depth_mm': -5})
        assert r.status_code == 400
        assert int(admin._dcim_store.items.get(dos['ia'])['depth_mm'] or 0) == 0

    def test_an_unknown_role_is_refused_when_mounted_or_only_edited(self, admin, client, dos):
        r = client.put(f'/api/v1/dcim/items/{dos["ia"]}', json={'role': 'nonsense'})
        assert r.status_code == 400
        r = client.post('/api/v1/dcim/items', json={'parent_uid': dos['ia'], 'role': 'nonsense',
                                                    'label': 'X'})
        assert r.status_code == 400
        assert not admin._dcim_store.children_of(dos['ia'])


class TestMountOnForeign:
    """D7 — mounting on an item is writing to it."""

    def test_mounting_on_another_companys_tray_is_refused(self, admin, client, dos):
        tray = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': dos['ka'], 'u_start': 10,
                                                            'label': 'TRAY-B'}))
        client.post('/api/v1/orgs/owner', json={'scope': 'item', 'uid': tray, 'org_uid': dos['b']})
        r = dos['ua'].post('/api/v1/dcim/items', json={'parent_uid': tray, 'label': 'MINI'})
        assert r.status_code == 403
        assert not admin._dcim_store.children_of(tray)
        # On one's own, it works.
        r = dos['ua'].post('/api/v1/dcim/items', json={'parent_uid': dos['ia'], 'label': 'MINI'})
        assert r.status_code == 200


class TestPartNumbers:
    """D8 — a new part: its numbers and its place checked like an edit."""

    def test_a_text_quantity_is_refused(self, admin, client, dos):
        r = client.post('/api/v1/dcim/parts', json={'item_uid': dos['ia'], 'kind': 'disk',
                                                    'qty': 'abc'})
        assert r.status_code == 400
        assert not admin._dcim_store.parts_of([dos['ia']])
        assert client.get(f'/api/v1/dcim/items/{dos["ia"]}/parts').status_code == 200

    def test_a_raw_place_is_cleaned(self, admin, client, dos):
        uid = _uid(client.post('/api/v1/dcim/parts', json={'item_uid': dos['ia'], 'kind': 'disk',
                                                           'place': '<script>'}))
        assert admin._dcim_store.parts.get(uid)['place'] == ''


class TestDanglingReferences:
    """D9 — what named a deleted item or piece stops naming it."""

    def test_deleting_an_item_unlinks_the_source_and_the_strip_that_were_it(self, admin, client, dos):
        st = admin._dcim_store
        ups = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': dos['ka'], 'u_start': 20,
                                                           'label': 'UPS'}))
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'S',
                                                             'kind': 'ups', 'item_uid': ups}))
        pdu = _uid(client.post('/api/v1/dcim/pdus', json={'rack_uid': dos['ka'], 'name': 'P',
                                                          'outlets': 8}))
        st.pdus.update(pdu, {'item_uid': ups})
        assert client.delete(f'/api/v1/dcim/items/{ups}').status_code == 200
        assert st.sources.get(src)['item_uid'] == ''
        assert st.pdus.get(pdu)['item_uid'] == ''

    def test_deleting_a_piece_unlinks_its_source(self, admin, client, dos):
        st = admin._dcim_store
        pieza = _uid(client.post('/api/v1/dcim/features', json={'room_uid': dos['ra'],
                                                                 'kind': 'panel'}))
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'C',
                                                             'feature_uid': pieza}))
        assert client.delete(f'/api/v1/dcim/features/{pieza}').status_code == 200
        assert st.sources.get(src)['feature_uid'] == ''

    def test_importing_a_plan_unlinks_the_sources_of_the_pieces_it_replaces(self, admin, client, dos):
        st = admin._dcim_store
        pieza = _uid(client.post('/api/v1/dcim/features', json={'room_uid': dos['ra'],
                                                                 'kind': 'panel'}))
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'C',
                                                             'feature_uid': pieza}))
        r = client.post(f'/api/v1/dcim/rooms/{dos["ra"]}/import',
                        json={'features': [{'kind': 'panel', 'pos_x': 1, 'pos_y': 1}]})
        assert r.status_code == 200, r.get_json()
        assert not st.features.get(pieza)
        assert st.sources.get(src)['feature_uid'] == ''


class TestRoomItemAssets:
    """D10 — a room item is numbered like any other."""

    def test_the_wildcard_is_minted_and_a_duplicate_refused(self, admin, client, dos):
        st = admin._dcim_store
        uno = _uid(client.post(f'/api/v1/dcim/rooms/{dos["ra"]}/items',
                               json={'role': 'pc', 'label': 'PC1', 'asset': 'RI-?'}))
        dos_ = _uid(client.post(f'/api/v1/dcim/rooms/{dos["ra"]}/items',
                                json={'role': 'pc', 'label': 'PC2', 'asset': 'RI-?'}))
        assert st.items.get(uno)['asset'] == 'RI-1'
        assert st.items.get(dos_)['asset'] == 'RI-2'
        r = client.put(f'/api/v1/dcim/room-items/{dos_}', json={'asset': 'RI-1'})
        assert r.status_code == 400
        assert st.items.get(dos_)['asset'] == 'RI-2'
        # Saving it without touching the number does not collide with itself.
        assert client.put(f'/api/v1/dcim/room-items/{uno}',
                          json={'asset': 'RI-1', 'label': 'PC1b'}).status_code == 200


class TestRoomToOtherSite:
    """D11 — a room moved to another site leaves the old site's sources behind."""

    def test_its_strips_and_its_ups_stop_hanging_from_the_old_site(self, admin, client, dos):
        st = admin._dcim_store
        sc = _uid(client.post('/api/v1/dcim/sites', json={'name': 'SC'}))
        sala = _uid(client.post('/api/v1/dcim/rooms', json={'site_uid': dos['sa'], 'name': 'M'}))
        rack = _uid(client.post('/api/v1/dcim/racks', json={'room_uid': sala, 'name': 'KM',
                                                            'u_height': 42}))
        ups = _uid(client.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 1,
                                                           'label': 'UPS'}))
        src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'Q'}))
        ups_src = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'U',
                                                                 'kind': 'ups', 'item_uid': ups}))
        pdu = _uid(client.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'P',
                                                          'outlets': 8, 'source_uid': src}))
        assert st.pdus.get(pdu)['source_uid'] == src
        assert client.put(f'/api/v1/dcim/rooms/{sala}', json={'site_uid': sc}).status_code == 200
        assert st.pdus.get(pdu)['source_uid'] == ''
        assert st.sources.get(ups_src)['item_uid'] == ''


class TestSourceChains:
    """D12 — a source's upstream and its clone respect whose each site is."""

    def test_a_source_does_not_hang_off_another_companys(self, admin, client, dos):
        ajena = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sb'], 'name': 'B'}))
        r = dos['ua'].post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'A',
                                                         'upstream_uid': ajena})
        assert r.status_code == 403
        mia = _uid(dos['ua'].post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'A'}))
        r = dos['ua'].put(f'/api/v1/dcim/sources/{mia}', json={'upstream_uid': ajena})
        assert r.status_code == 403
        assert admin._dcim_store.sources.get(mia)['upstream_uid'] == ''

    def test_a_clone_does_not_write_into_a_site_the_caller_cannot_write(self, admin, client, dos):
        st = admin._dcim_store
        raiz = _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sa'], 'name': 'R'}))
        _uid(client.post('/api/v1/dcim/sources', json={'site_uid': dos['sb'], 'name': 'H',
                                                       'upstream_uid': raiz}))
        antes = len(st.sources.list())
        r = dos['ua'].post(f'/api/v1/dcim/sources/{raiz}/clone')
        assert r.status_code == 403
        assert len(st.sources.list()) == antes


class TestBuildFiles:
    """D13 — a template's files go with the template's permissions, not the catalogue's."""

    def test_who_attaches_to_a_template_can_read_and_remove_it(self, admin, client):
        _login(client)
        c = _login_as(admin, 'tpl', perms=['dcim_view', 'dcim_build_edit'])
        b = _uid(c.post('/api/v1/dcim/builds', json={'name': 'B1'}))
        r = c.post(f'/api/v1/dcim/builds/{b}/files?name=quote.pdf', data=b'%PDF-1.4 x',
                   content_type='application/octet-stream')
        f = _uid(r)
        assert c.get(f'/api/v1/dcim/files/{f}').status_code == 200
        # The catalogue's managers are not the template's: they do not remove it.
        cm = _login_as(admin, 'catm', perms=['dcim_catalog_view', 'dcim_catalog_manage'])
        assert cm.delete(f'/api/v1/dcim/files/{f}').status_code == 403
        assert c.delete(f'/api/v1/dcim/files/{f}').status_code == 200
