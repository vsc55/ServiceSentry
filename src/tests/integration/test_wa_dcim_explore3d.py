#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""/3d — the inventory in 3D as a page of its own.

Asked for: take the 3D out to a separate page like /status, but behind a login: the sites on a
map with their state, a click on one opens it as a building, and from there the building or
floor by floor, walking its floors and going from one site to another. Without touching what
the panel already does — so the page reuses the panel's pieces and redefines, only for itself,
the few functions through which those pieces go back to the panel.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run                                  # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


@pytest.fixture(scope='module')
def wa():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    w = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    w._csrf_enabled = False
    w.app.config['TESTING'] = True
    return w


class TestTheRoute:

    def test_a_guest_goes_to_the_login(self, wa):
        r = wa.app.test_client().get('/3d')
        assert r.status_code == 302 and '/login' in r.headers['Location']

    def test_without_dcim_view_the_panel_instead(self, wa, monkeypatch):
        c = wa.app.test_client()
        _login(c)
        monkeypatch.setattr(wa, '_get_session_permissions', lambda: ['dashboard_view'])
        r = c.get('/3d')
        assert r.status_code == 302 and r.headers['Location'].endswith('/admin')

    def test_the_page_its_stage_and_not_the_panel(self, wa):
        c = wa.app.test_client()
        _login(c)
        r = c.get('/3d')
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and 'no-store' in r.headers.get('Cache-Control', '')
        assert 'id="x3-main"' in html and 'id="x3-crumbs"' in html
        # The engine and the site's 3D, the panel's own; not the panel's sections.
        assert 'function ss3dMount' in html and 'function _ds3Scene' in html
        assert 'function renderModules' not in html and 'id="tab-dcim"' not in html


_PROBE = r"""
__out = {};
// The panel's pieces call these when something changes; here they redraw THIS page.
__out.redefinidas = {
    render: String(renderDcim).includes('_x3Render'),
    sede: String(_dcimBoardGoSite).includes('_x3OpenSite'),
    modo: String(_ds3SetMode).includes('_x3Go'),
    // The viewer's own walking button starts the game walk here, not the engine's orbit walk
    // (keys only with the canvas focused, stepping, F for «home view»).
    muneco: String(ss3dWalk).includes('_x3Walk'),
    // And the pointer is captured inside the click, before waiting for the view to change.
    capturaAntes: String(_x3Walk).indexOf('requestPointerLock') < String(_x3Walk).indexOf('await'),
};
// What opens a panel screen opens it in the panel, in another tab.
const abiertas = [];
window.open = (u) => abiertas.push(u);
_dcimLoadRack('k1');
_dcimOpenDevice('d1');
__out.alPanel = abiertas;

// Where one is: Sites › the site › its floors, bottom to top, the current one marked.
_dcimData = {sites: [{uid: 's1', name: 'Demo', rooms: [{uid: 'r1', floor_uid: 'f2'}]},
                     {uid: 's2', name: 'Otra', rooms: []}]};
_dcimBoard = {sites: [{uid: 's1', state: 'error'}]};
_x3View = 'site';
_dcsPlan = {site: {uid: 's1', name: 'Demo'}, floor: 'f1',
            floors: [{uid: 'f2', name: 'Primera', level: 1}, {uid: 'f1', name: 'Baja', level: 0}]};
const migas = _x3CrumbsHtml();
__out.migas = {
    sedes: migas.includes(t('x3_sites')),
    otraSede: migas.includes('value="s2"') && migas.includes('value="s1" selected'),
    orden: migas.indexOf('Baja') < migas.indexOf('Primera'),
    marcada: /btn-primary"\s*onclick="_x3Go\([^)]*f1/.test(migas.replace(/&quot;/g, '"')),
    bajarNo: /_x3Step\(-1\)"\s*disabled/.test(migas),
};
__out.plantas = _x3Floors().map(f => f.uid);
__out.sala = (_x3Room('r1') || {}).floor_uid;

// Walking: a click on a closed rack opens it where it stands; F opens or closes the one in
// front, also through one of its items; anything else is not «used» (its card shows instead).
const abiertos = [];
_x3OpenRack = (uid) => abiertos.push(uid);
_dc3dOpenRacks.clear();
__out.usar = {
    rack: _x3Use({tipo: 'rack', uid: 'k1'}, 'click'),
    equipoClic: _x3Use({tipo: 'item', uid: 'i', rack: 'k1'}, 'click'),
    equipoF: _x3Use({tipo: 'item', uid: 'i', rack: 'k2'}, 'toggle'),
    puerta: _x3Use({tipo: 'feature', uid: 'd'}, 'click'),
};
// What can be done with what one aims at, said by the crosshair.
__out.aviso = {
    cerrado: _x3AimHint({tipo: 'rack', uid: 'k9', name: 'H08'}, {}),
    escalera: _x3AimHint(null, {stairs: true}),
    nada: _x3AimHint(null, {}),
};
_dc3dOpenRacks.set('k3', {});
__out.aviso.abierto = _x3AimHint({tipo: 'rack', uid: 'k3', name: 'H03'}, {});
__out.usar.abiertoClic = _x3Use({tipo: 'rack', uid: 'k3'}, 'click');
__out.usar.abiertoF = _x3Use({tipo: 'rack', uid: 'k3'}, 'toggle');
__out.abiertos = abiertos;
_dc3dOpenRacks.clear();

// The address says where one is, so a link or F5 comes back to it.
let escrita = '';
globalThis.history = {pushState: (_s, _t, u) => { escrita = u; },
                      replaceState: (_s, _t, u) => { escrita = u; }};
window.location = {href: 'http://x/3d', pathname: '/3d', search: '', hash: ''};
_ds3Mode = 'floor';
_x3Url(true);
__out.direccion = escrita;
// Seen in the browser: changing floor never entered the history, and «back» skipped the whole
// page. `_dcsGo` (the panel's) calls `_dcimUrl` midway; it must not write the address, or the
// push that follows finds nothing to add.
const pasos = [];
globalThis.history = {pushState: (_s, _t, u) => pasos.push(['push', u]),
                      replaceState: (_s, _t, u) => pasos.push(['replace', u])};
window.location = {href: 'http://x' + escrita, pathname: '/3d', search: escrita.slice(3), hash: ''};
_dcsPlan.floor = 'f2';
_dcimUrl();
_x3Url(true);
__out.historial = pasos;
// The sites by state in the map's header: how many of each, the down ones beating, a state with
// none not pressable, and each button pointing out the next site of its state on the map.
_dcimBoard = {sites: [{uid: 'a', state: 'ok'}, {uid: 'b', state: 'error'}, {uid: 'c', state: ''},
                      {uid: 'd', state: 'error'}, {uid: 'e', state: 'maintenance'}]};
__out.cuentas = _x3SumCounts(_dcimBoard.sites);
_x3View = 'map';
const cab = _x3CrumbsHtml();
__out.resumen = {botones: (cab.match(/_x3SumGo\(/g) || []).length, late: cab.includes('ss-glow-danger'),
                 avisoApagado: (cab.split('<button').find(x => x.includes('btn-warning') && x.includes('_x3SumGo')) || '').includes('disabled')};
const senaladas = [];
_dcmRaise = (uid) => senaladas.push(uid);
_x3SumGo('error'); _x3SumGo('error'); _x3SumGo('error');
__out.senaladas = senaladas;
// The «3D» button of a plan or a rack: the camera flies to the room asked for, or the rack opens.
const vuelos = [], abiertos3d = [];
ss3dGet = () => ({escena: {cajas: [{}], salas: [{uid: 'r1', y: 3, frame: {x: 2, z: 4, W: 6, D: 8, rot: 0}}]}});
ss3dFlyTo = (V, d) => vuelos.push(d);
_dc3dOpenRack = (uid) => abiertos3d.push(uid);
_x3Focus('r1', '');
_x3Focus('', 'k7');
_x3Focus('nada', '');
__out.enfoque = {vuelos, abiertos: abiertos3d};
"""


class TestThePage:

    @pytest.fixture(scope='class')
    def out(self, wa):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        c = wa.app.test_client()
        _login(c)
        html = c.get('/3d').get_data(as_text=True)
        guion = max(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S), key=len)
        return node_run(guion, _PROBE)

    def test_the_maps_header_sums_the_sites_by_state(self, out):
        """Asked for: beside «Sites», how many are ok, in warning and down (and unwatched, so the
        numbers add up). The down ones beat; a state with none cannot be pressed; each button
        points out on the map the next site in that state."""
        assert out['cuentas'] == {'ok': 1, 'warning': 0, 'error': 2, '': 2}
        r = out['resumen']
        assert r['botones'] == 4 and r['late'] and r['avisoApagado']
        assert out['senaladas'] == ['b', 'd', 'b']

    def test_the_panels_pieces_redraw_this_page(self, out):
        assert out['redefinidas'] == {'render': True, 'sede': True, 'modo': True, 'muneco': True,
                                      'capturaAntes': True}

    def test_a_rack_or_a_device_opens_in_the_panel(self, out):
        assert out['alPanel'] == ['/dcim?rack=k1', '/infra?device=d1']

    def test_where_one_is_sites_the_site_and_its_floors(self, out):
        assert out['migas'] == dict.fromkeys(('sedes', 'otraSede', 'orden', 'marcada', 'bajarNo'), True)
        assert out['plantas'] == ['f1', 'f2'] and out['sala'] == 'f2'

    def test_it_goes_to_the_room_or_rack_the_address_asks_for(self, out):
        """The «3D» link of a room's plan or a rack sends `room` or `rack`: the camera flies to
        the room's middle, or the rack opens in its place; one that is not there does nothing."""
        e = out['enfoque']
        assert e['vuelos'] == [{'mira': [5, 4, 8], 'radio': 11.2}]
        assert e['abiertos'] == ['k7']

    def test_the_address_says_where_one_is(self, out):
        assert out['direccion'].endswith('?site=s1&floor=f1&mode=floor')

    def test_walking_a_click_opens_a_rack_and_f_toggles_the_one_ahead(self, out):
        """Reported from the screen: walking in the HPC room, clicking a rack offered no way to
        open it — the pointer was captured, so the card's buttons could not be pressed."""
        assert out['usar'] == {'rack': True, 'equipoClic': False, 'equipoF': True, 'puerta': False,
                               'abiertoClic': False, 'abiertoF': True}
        assert out['abiertos'] == ['k1', 'k2', 'k3']

    def test_the_crosshair_says_what_can_be_done(self, out):
        """Asked for: a message saying which key to press on what can be used."""
        a = out['aviso']
        assert 'H08' in a['cerrado'] and 'F' in a['cerrado']
        assert 'H03' in a['abierto'] and a['abierto'] != a['cerrado'].replace('H08', 'H03')
        assert 'E' in a['escalera'] and 'Q' in a['escalera'] and a['nada'] == ''

    def test_changing_floor_enters_the_history(self, out):
        assert out['historial'] == [['push', '/3d?site=s1&floor=f2&mode=floor']]
