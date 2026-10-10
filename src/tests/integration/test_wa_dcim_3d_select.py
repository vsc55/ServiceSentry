#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Highlighting in the 3D what is clicked (`_select3d.html`).

Asked for: select a network line, a power line, a server or a device in the 3D and have it
stand out — the cable from a server to its switch, or one link from a floor to another, that
cable alone. What is clicked and what belongs to it keeps its colour (the lines, thicker);
everything else fades. A device brings its whole path, from the trace; a bundle lists its
cables, and one of them is drawn alone over the faded bundle.

The arithmetic runs in node against the panel's own bundle; the data it needs comes from the
circuits (each run with its cables) and the trace (each hop with its rack and room).
"""

from __future__ import annotations

import shutil

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


class TestTheData:
    """Two racks on two floors, a server cabled to its switch, the switch up to the core."""

    @pytest.fixture()
    def site(self, client):
        _login(client)
        c = client
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        f1 = _uid(c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P1'}))
        f2 = _uid(c.post('/api/v1/dcim/floors', json={'site_uid': site, 'name': 'P2'}))
        r1 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD', 'floor_uid': f1}))
        r2 = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'IDF', 'floor_uid': f2}))
        k1 = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r1, 'name': 'N01', 'u_height': 42}))
        k2 = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': r2, 'name': 'IDF-P2', 'u_height': 42}))
        core = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k1, 'u_start': 40, 'role': 'switch',
                                                       'label': 'CORE-1'}))
        sw = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k2, 'u_start': 30, 'role': 'switch',
                                                     'label': 'SW-P2-1'}))
        srv = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': k2, 'u_start': 1, 'role': 'server',
                                                      'label': 'srv-1'}))
        up = _uid(c.post('/api/v1/dcim/cables', json={'a_item': sw, 'a_port': 'Te1/1/1', 'b_item': core,
                                                      'b_port': 'Te1/0/29', 'kind': 'fiber',
                                                      'label': 'P2-CORE1'}))
        _uid(c.post('/api/v1/dcim/cables', json={'a_item': srv, 'a_port': 'eth0', 'b_item': sw,
                                                 'b_port': 'Gi1/0/1'}))
        return dict(site=site, k1=k1, k2=k2, core=core, sw=sw, srv=srv, up=up, r2=r2)

    def test_a_run_between_floors_lists_its_cable_with_both_ends_named(self, client, site):
        d = client.get(f'/api/v1/dcim/sites/{site["site"]}/circuits').get_json()
        assert len(d['net']) == 1
        cables = d['net'][0]['cables']
        assert [(c['uid'], c['an'], c['ap'], c['bn'], c['bp'], c['kind']) for c in cables] \
            in ([(site['up'], 'SW-P2-1', 'Te1/1/1', 'CORE-1', 'Te1/0/29', 'fiber')],
                [(site['up'], 'CORE-1', 'Te1/0/29', 'SW-P2-1', 'Te1/1/1', 'fiber')])

    def test_each_hop_of_a_trace_says_its_rack_and_room(self, client, site):
        d = client.get(f'/api/v1/dcim/items/{site["srv"]}/trace').get_json()
        hops = d['paths'][0]
        assert [(h['label'], h['rack']) for h in hops] == [('srv-1', site['k2']), ('SW-P2-1', site['k2'])]
        assert all('room' in h for h in hops)


_PROBE = r"""
__out = {};
const circ = {
  net: [{a: 'k1', b: 'k2', total: 2, kinds: {fiber: 2}, cables: [
          {uid: 'c1', a: 'sw', ap: 'Te1/1/1', an: 'SW-P2-1', b: 'core', bp: 'Te1/0/29', bn: 'CORE-1', kind: 'fiber', label: 'UP-1'},
          {uid: 'c2', a: 'sw2', ap: 'Te1/1/1', an: 'SW-P2-2', b: 'core', bp: 'Te1/0/30', bn: 'CORE-1', kind: 'fiber', label: 'UP-2'}]}],
  hnet: [{room: 'r', rack: 'k2', total: 1, kinds: {copper: 1}, cables: [
          {uid: 'h1', a: 'out', ap: 'A-R', an: 'P2.01', b: 'pp', bp: '1', bn: 'Panel', kind: 'copper', label: ''}]}],
  power: [{rack: 'k2', pdu: 'p', name: 'PDU', feed: 'a', source: 's1'}],
  sources: [{uid: 's1', name: 'SAI', kind: 'ups'}]};
const sets = (s) => ({key: s.key, items: [...s.items].sort(), racks: [...s.racks].sort(),
                      cables: [...s.cables].sort(), runs: [...s.runs].sort(), power: [...s.power].sort(),
                      sources: [...s.sources].sort(), rooms: [...s.rooms].sort()});
__out.rack = sets(_dc3dSelFrom({tipo: 'rack', uid: 'k2'}, circ));
__out.run = sets(_dc3dSelFrom({tipo: 'run', key: 'run:k1|k2'}, circ));
__out.cable = sets(_dc3dSelFrom({tipo: 'cable', uid: 'c1'}, circ));
__out.power = sets(_dc3dSelFrom({tipo: 'power', key: 'pw:k2|s1', rack: 'k2', source: 's1'}, circ));
__out.source = sets(_dc3dSelFrom({tipo: 'source', uid: 's1'}, circ));
const item = _dc3dSelFrom({tipo: 'item', uid: 'sw', rack: 'k2'}, circ);
_dc3dSelAddPaths(item, [[{item: 'sw', rack: 'k2', cable: null},
                         {item: 'core', rack: 'k1', room: 'cpd', cable: {uid: 'c1'}}]]);
__out.item = sets(item);

// Applied to a scene: what is not selected fades and stays pickable; the selected line thickens;
// a wall (no `lee`) is left alone.
_dc3dSel = _dc3dSelFrom({tipo: 'cable', uid: 'c1'}, circ);
const tubo = ss3dTube([0, 2, 0], [4, 2, 0], 0.02);
const escena = {cajas: [
  {color: [0.5, 0.5, 0.5, 1], m: ss3dModel(0, 0, 0, 0.6, 2, 1, 0), lee: {tipo: 'rack', uid: 'k1'}},
  {color: [0.5, 0.5, 0.5, 1], m: ss3dModel(5, 0, 0, 0.6, 2, 1, 0), lee: {tipo: 'rack', uid: 'k9'}},
  {color: [0.9, 0.9, 0.9, 1], m: ss3dModel(0, 0, 0, 10, 3, 0.1, 0), lee: null},
  {color: [1, 0.5, 0, 1], m: tubo, lee: {tipo: 'cable', uid: 'c1'}}]};
_dc3dSelApply(escena);
const [r1, r9, muro, cab] = escena.cajas;
__out.halos = escena.cajas.filter(k => !k.lee && k.color[0] === 1 && k.color[3] < 0.5).length;
const grosor = (m) => [0, 4, 8].map(i => Math.hypot(m[i], m[i + 1], m[i + 2])).sort((a, b) => a - b)[0];
__out.apply = {r1: r1.color[3], r9: r9.color[3], muro: muro.color[3],
               r9pick: _dc3dPickable(r9), cab: Math.round(grosor(cab.m) / grosor(tubo) * 10) / 10,
               largo: Math.round(Math.max(...[0, 4, 8].map(i => Math.hypot(cab.m[i], cab.m[i + 1], cab.m[i + 2]))) * 100) / 100};

// And the three viewers apply it: it goes through what each calls last on its scene.
const vista = {cajas: [{color: [0.5, 0.5, 0.5, 1], m: ss3dModel(5, 0, 0, 0.6, 2, 1, 0),
                        lee: {tipo: 'rack', uid: 'k9'}}]};
_dc3dAddFoco(vista);
__out.enLosVisores = vista.cajas[0].color[3];

// One cable of a bundle selected: the bundle fades, and that cable alone is drawn over it.
const cajas = [];
_dc3dOneCable(cajas, circ.net[0], [0, 2, 0], [4, 2, 3], 2.4);
__out.uno = {n: cajas.length, uid: (cajas[0] || {}).lee && cajas[0].lee.uid};
_dc3dSel = _dc3dSelFrom({tipo: 'run', key: 'run:k1|k2'}, circ);
const otras = [];
_dc3dOneCable(otras, circ.net[0], [0, 2, 0], [4, 2, 3], 2.4);
__out.mazo = otras.length;

// The card of a run lists its cables, and offers to clear the highlight.
_dc3dCirc = {site: 's', data: circ, loading: ''};
const ficha = _dc3dRunCablesHtml('run:k1|k2') + _dc3dSelBar();
__out.ficha = {botones: (ficha.match(/_dc3dSelectCable\(/g) || []).length, nombre: ficha.includes('SW-P2-1 Te1/1/1 ↔ CORE-1 Te1/0/29'),
               quitar: ficha.includes('_dc3dSelClear()')};
_dc3dSel = null;
__out.sinSel = _dc3dSelBar();

// A device's connections, one per port; one port, only what it connects.
const sw = _dc3dSelFrom({tipo: 'item', uid: 'sw', rack: 'k2'}, circ);
sw.lee = {tipo: 'item', uid: 'sw', rack: 'k2'};
sw.paths = [
  [{item: 'sw', port: 'Te1/1/1', rack: 'k2', cable: null}, {item: 'fp', label: 'Fibra', port: '1', rack: 'k2', cable: {uid: 'c9'}},
   {item: 'core', label: 'CORE-1', port: 'Te1/0/29', rack: 'k1', cable: {uid: 'c1'}}],
  [{item: 'sw', port: 'Gi1/0/1', rack: 'k2', cable: null}, {item: 'pc', label: 'PC-1', port: 'eth0', room: 'r', cable: {uid: 'c5'}}]];
_dc3dSelAddPaths(sw, sw.paths);
const uno = _dc3dSelPort(sw, 1);
__out.puerto = {items: [...uno.items].sort(), cables: [...uno.cables].sort(), racks: [...uno.racks].sort(),
                base: uno.base === sw, todoAntes: [...sw.cables].sort()};
const lista = _dc3dPortsHtml(sw), listaUno = _dc3dPortsHtml(uno);
__out.lista = {filas: (lista.match(/_dc3dSelectPort\(/g) || []).length,
               texto: lista.includes('Te1/1/1 → CORE-1 Te1/0/29'), todas: lista.includes('_dc3dSelectAll()'),
               activa: (listaUno.match(/btn-warning/g) || []).length, todasEnUno: listaUno.includes('_dc3dSelectAll()')};

// Opening a rack is looking inside it: its own selection goes (its content would fade); another
// thing's —a run— stays.
_dc3dSel = _dc3dSelFrom({tipo: 'rack', uid: 'k2'}, circ);
_dc3dSelOpening('k2');
const tras = _dc3dSel;
_dc3dSel = _dc3dSelFrom({tipo: 'run', key: 'run:k1|k2'}, circ);
_dc3dSelOpening('k2');
__out.abrir = [tras === null, !!_dc3dSel];
"""


class TestTheArithmetic:

    @pytest.fixture()
    def out(self, client):
        if shutil.which('node') is None:
            pytest.skip('no node: nothing to run the script with')
        _login(client)
        return node_run(panel_bundle(client), _PROBE)

    def test_a_rack_brings_its_runs_and_its_power(self, out):
        r = out['rack']
        assert r['racks'] == ['k2'] and r['runs'] == ['hnet:r|k2', 'run:k1|k2']
        assert r['power'] == ['pw:k2|s1'] and r['sources'] == ['s1']

    def test_a_run_brings_its_cables_its_racks_and_their_ends(self, out):
        r = out['run']
        assert r['runs'] == ['run:k1|k2'] and r['racks'] == ['k1', 'k2']
        assert r['cables'] == ['c1', 'c2'] and r['items'] == ['core', 'sw', 'sw2']

    def test_a_cable_is_itself_and_its_two_ends(self, out):
        c = out['cable']
        assert c['cables'] == ['c1'] and c['runs'] == [] and c['items'] == ['core', 'sw']
        assert c['racks'] == ['k1', 'k2']

    def test_power_a_line_or_a_source_with_its_racks(self, out):
        assert out['power']['power'] == ['pw:k2|s1'] and out['power']['racks'] == ['k2']
        assert out['source']['sources'] == ['s1'] and out['source']['power'] == ['pw:k2|s1']

    def test_a_device_brings_its_cables_and_its_whole_path(self, out):
        i = out['item']
        assert i['items'] == ['core', 'sw']
        assert 'c1' in i['cables'] and i['racks'] == ['k1', 'k2']

    def test_the_rest_fades_and_stays_pickable_and_the_line_thickens(self, out):
        a = out['apply']
        assert a['r1'] == 1 and a['r9'] <= 0.1 and a['muro'] == 1
        assert a['r9pick'] is True
        assert out['enLosVisores'] <= 0.1
        assert a['cab'] == 2.5 and a['largo'] == 4
        assert out['halos'] == 1          # the rack at the selected cable's end

    def test_one_cable_of_a_bundle_is_drawn_alone_over_it(self, out):
        assert out['uno']['n'] >= 1 and out['uno']['uid'] == 'c1'
        assert out['mazo'] == 0          # the whole run selected: no extra line, the run itself

    def test_a_device_lists_its_connections_and_one_port_shows_only_its_own(self, out):
        """Asked for: selecting a device shows everything connected to it, and selecting one of
        its ports only what that port connects. Its card lists one connection per port, from
        its port to what is at the other end; clicking one narrows to that path, and «All
        connections» goes back."""
        p = out['puerto']
        assert p['items'] == ['pc', 'sw'] and p['cables'] == ['c5'] and p['racks'] == ['k2']
        assert p['base'] and {'c1', 'c5', 'c9'} <= set(p['todoAntes'])
        li = out['lista']
        assert li['filas'] == 2 and li['texto'] and not li['todas']
        assert li['activa'] == 1 and li['todasEnUno']

    def test_opening_the_selected_rack_shows_what_is_inside(self, out):
        """Reported: opening a rack worked only on foot. In the other views the click selected
        it first, and its content —not part of the selection— came out faded: an open rack that
        looked empty. Opening it drops its own selection; another's stays."""
        assert out['abrir'] == [True, True]

    def test_a_runs_card_lists_its_cables_and_offers_to_clear(self, out):
        f = out['ficha']
        assert f['botones'] == 2 and f['nombre'] and f['quitar']
        assert out['sinSel'] == ''
