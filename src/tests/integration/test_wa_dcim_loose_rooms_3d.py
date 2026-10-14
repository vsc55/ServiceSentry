#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rooms on no floor, in 3D.

Reported: a site with no floors and only a technical room (the demo's backup site) opened in /3d
as «this site has no floors» and drew nothing of that room. The 3D draws floors and the rooms
placed on them, and the site's contents (`/api/v1/dcim/sites/<uid>/contents`) skipped every
room without a floor, so its racks never reached the page.

Now those rooms are seen on a floor that does not exist, «Rooms without a floor», laid side by
side: the contents carry them (filtered as any other), a site made only of them opens straight
into that floor, and the message stays for a site with neither floors nor rooms. The floor is
only for looking — the floor-plan editor does not offer it.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest

from tests.conftest import _login, _login_as                       # noqa: E402
from tests.helpers import node_run                                  # noqa: E402

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
def backup(client):
    """A backup site with no floors: two rooms of its own — one with a rack — and one of
    another company, with a rack of that company."""
    _login(client)
    c = client
    mine = _uid(c.post('/api/v1/orgs', json={'name': 'Grupo', 'short': 'GR'}))
    other = _uid(c.post('/api/v1/orgs', json={'name': 'Ajena', 'short': 'AJ'}))
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Respaldo'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': site, 'org_uid': mine})
    cpd = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD respaldo',
                                                  'width_mm': 6000, 'depth_mm': 4000}))
    rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': cpd, 'name': 'RB-01',
                                                   'u_height': 42}))
    ups = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Almacén',
                                                  'width_mm': 3000, 'depth_mm': 2000}))
    foreign = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Jaula ajena'}))
    c.post('/api/v1/orgs/owner', json={'scope': 'room', 'uid': foreign, 'org_uid': other})
    frack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': foreign, 'name': 'AJ-SECRETO',
                                                    'u_height': 42}))
    c.post('/api/v1/orgs/owner', json={'scope': 'rack', 'uid': frack, 'org_uid': other})
    empty = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Solar'}))
    return dict(site=site, cpd=cpd, rack=rack, ups=ups, foreign=foreign, frack=frack,
                mine=mine, other=other, empty=empty)


class TestTheContents:

    def test_a_loose_room_brings_its_racks(self, client, backup):
        d = client.get(f'/api/v1/dcim/sites/{backup["site"]}/contents').get_json()
        assert [r['name'] for r in d['rooms'][backup['cpd']]['racks']] == ['RB-01']
        assert backup['ups'] in d['rooms']
        # The shape is the one it always was.
        assert set(d) == {'rooms', 'kinds', 'walls'}
        assert {'racks', 'features', 'items', 'rows'} <= set(d['rooms'][backup['cpd']])

    def test_a_foreign_loose_room_is_not_leaked(self, admin, backup):
        c = _login_as(admin, 'solo-grupo', ['dcim_view', f'org.{backup["mine"]}.view'])
        r = c.get(f'/api/v1/dcim/sites/{backup["site"]}/contents')
        assert r.status_code == 200
        d = r.get_json()
        assert [k['name'] for k in d['rooms'][backup['cpd']]['racks']] == ['RB-01']
        ajena = d['rooms'].get(backup['foreign'], {})
        assert ajena.get('racks', []) == [] and ajena.get('features', []) == []
        assert 'AJ-SECRETO' not in r.get_data(as_text=True)


_PROBE = r"""
__out = {};
currentUser = {permissions: ['dcim_view']};
const DATA = __DATA__;
const guardados = {};
const nativo = document.getElementById;
document.getElementById = (id) => guardados[id] || (guardados[id] = nativo(id));
_dc3dMount = () => {};
p2dEnsureKinds = async () => {};
globalThis.history = {pushState() {}, replaceState() {}};
window.location = {href: 'http://x/3d', pathname: '/3d', search: '', hash: ''};
const main = () => document.getElementById(_X3_MAIN).innerHTML;
const rack = (e, uid) => e.cajas.some(k => k.lee && k.lee.tipo === 'rack' && String(k.lee.uid) === uid);

__wait = (async () => {
    // The page boots on its own (`_x3Load`, then the map): let it finish before taking over.
    for (let i = 0; i < 50; i++) await null;
    _dcimData = {sites: DATA.sites};
    _dcimBoard = {sites: []};
    apiGet = async (url) => {
        const m = url.match(/sites\/([^/]+)\/(floors|contents)/);
        return m ? DATA[m[2]][m[1]] : {};
    };
    // A site with no floors and only loose rooms: straight into the virtual floor.
    await _x3OpenSite(DATA.site, '', 'building', true);
    const edificio = _ds3Scene();
    _ds3Mode = 'floor';
    const planta = _ds3Scene();
    __out.sola = {
        plantas: _dcsPlan.floors.map(f => [f.uid, f.name, !!f.virtual]),
        floor: _dcsPlan.floor,
        sinPlantas: main().includes(t('x3_no_floors')),
        visor: main().includes('ss-stage'),
        nombre: t('x3_loose_floor'),
        boton: document.getElementById(_X3_CRUMBS).innerHTML.includes(t('x3_loose_floor')),
        salas: planta.salas.map(s => [s.name, s.frame.x, s.frame.z, s.frame.W, s.frame.rot]),
        rack: rack(planta, DATA.rack),
        rackEdificio: rack(edificio, DATA.rack),
    };
    // A site with neither floors nor rooms: the message, as before.
    await _x3OpenSite(DATA.empty, '', 'building', true);
    __out.vacia = {plantas: _dcsPlan.floors.length, sinPlantas: main().includes(t('x3_no_floors'))};
    // The «3D» link of a loose room or a rack in one: to the virtual floor, the room asked for.
    __out.enlace = [_dc3dLinkHtml({site: DATA.site, floor: '', room: DATA.cpd}),
                    _dc3dLinkHtml({site: DATA.site, floor: '', rack: DATA.rack})];
    // Opened from that link: the virtual floor, even if the site had real ones.
    DATA.floors[DATA.site] = {floors: [{uid: 'f0', name: 'Baja', level: 0}], kinds: {}};
    await _x3OpenSite(DATA.site, _DS3_LOOSE, 'floor', true);
    __out.pedida = {floor: _dcsPlan.floor, orden: _x3Floors().map(f => f.uid)};
    // In the building, the loose rooms stand beside it, at street level; a double click on one
    // goes to its floor.
    await _x3Go('f0', 'building');
    const junto = _ds3Scene();
    __out.junto = {rack: rack(junto, DATA.rack),
                   x: Math.min(...junto.cajas.filter(k => k.lee && k.lee.tipo === 'rack').map(k => k.m[12]))};
    await _dcimOpenPlan(DATA.cpd);
    __out.dobleClic = _dcsPlan.floor;
})();
"""


class TestThePage:

    @pytest.fixture()
    def out(self, client, backup):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        html = client.get('/3d').get_data(as_text=True)
        guion = max(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S), key=len)
        b = backup
        data = {
            'site': b['site'], 'empty': b['empty'], 'cpd': b['cpd'], 'rack': b['rack'],
            'sites': client.get('/api/v1/dcim/sites').get_json()['sites'],
            'floors': {s: client.get(f'/api/v1/dcim/sites/{s}/floors').get_json()
                       for s in (b['site'], b['empty'])},
            'contents': {s: client.get(f'/api/v1/dcim/sites/{s}/contents').get_json()
                         for s in (b['site'], b['empty'])},
        }
        return node_run(guion, _PROBE.replace('__DATA__', json.dumps(data)))

    def test_a_floorless_site_opens_on_the_virtual_floor(self, out):
        s = out['sola']
        assert s['nombre'] in ('Rooms without a floor', 'Salas sin planta')
        assert s['plantas'] == [['_loose', s['nombre'], True]]
        assert s['floor'] == '_loose'
        assert not s['sinPlantas'] and s['visor'] and s['boton']

    def test_the_loose_rooms_side_by_side_with_their_racks(self, out):
        """By name, unturned, 2 m apart, each at its own width (no size: the 4 m placeholder)."""
        s = out['sola']
        assert s['salas'] == [['Almacén', 0, 0, 3, 0], ['CPD respaldo', 5, 0, 6, 0],
                              ['Jaula ajena', 13, 0, 4, 0]]
        assert s['rack'] and s['rackEdificio']

    def test_neither_floors_nor_rooms_still_says_so(self, out):
        assert out['vacia'] == {'plantas': 0, 'sinPlantas': True}

    def test_the_link_of_a_loose_room_or_rack_goes_to_the_virtual_floor(self, out):
        sala, rk = out['enlace']
        assert 'floor=_loose' in sala and 'room=' in sala and 'mode=floor' in sala
        assert 'floor=_loose' in rk and 'rack=' in rk

    def test_asked_for_it_goes_there_and_it_is_the_last_floor(self, out):
        assert out['pedida'] == {'floor': '_loose', 'orden': ['f0', '_loose']}

    def test_in_the_building_beside_it_and_a_double_click_goes_there(self, out):
        assert out['junto']['rack'] and out['junto']['x'] > 20
        assert out['dobleClic'] == '_loose'
