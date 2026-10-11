#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The jacks of a wall outlet and of a power socket, and —a power socket— the power source it
hangs from.

Asked for: there was nowhere to say that a socket is fed from the UPS or the generator, and a
fibre outlet looked like a copper one. Then: a plate is not of one kind — two RJ45, a fibre and
an HDMI; two Schuko and a C13. So a socket is a room item (`power_outlet`) like the outlet, and
both keep a LIST of jacks, each a connector from the connector catalogue (copper, fibre and video
for an outlet; power for a socket) and how many —a whole number from 1, with no maximum—. A
socket chooses one of its site's sources and inherits its whole chain.

With app and session for the routes; the drawing and the card in `node`.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle, plan2d_catalog_js  # noqa: E402

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
def sala(client):
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    otra = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Otra'}))
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'Oficina'}))
    sai = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': site, 'name': 'SAI-1', 'kind': 'ups'}))
    ajena = _uid(c.post('/api/v1/dcim/sources', json={'site_uid': otra, 'name': 'SAI-X', 'kind': 'ups'}))
    return dict(site=site, room=room, sai=sai, ajena=ajena)


class TestWhatAJackCanBe:

    def test_an_outlet_is_copper_fibre_or_video_and_a_socket_is_power(self, client):
        _login(client)
        d = client.get('/api/v1/dcim/room-items/jacks').get_json()
        roseta = {c['id']: c['abbr'] for c in d['connectors']['outlet']}
        toma = {c['id']: c['abbr'] for c in d['connectors']['power_outlet']}
        assert roseta['8p8c'] == 'RJ45' and roseta['6p4c'] == 'RJ11' and roseta['6p6c'] == 'RJ12'
        assert roseta['lc-upc'] == 'LC' and '8p4c' not in roseta, 'an 8P4C is no wall jack'
        assert 'hdmi' in roseta, 'a multimedia plate has an HDMI'
        assert '1000base-t' not in roseta and '10gbase-x-sfpp' not in roseta and 'splice' not in roseta
        assert toma['cee-7-3'] == 'SCH' and toma['iec-60320-c13'] == 'C13' and toma['iec-60320-c14'] == 'C14'
        assert '8p8c' not in toma and 'cee-7-3' not in roseta
        assert 'cee-7-7' not in toma, 'a Schuko PLUG is not a wall socket'


class TestAPlateOfSeveralKinds:

    def test_a_socket_keeps_its_jacks_and_source_and_draws_them(self, client, sala):
        c = client
        uid = _uid(c.post(f'/api/v1/dcim/rooms/{sala["room"]}/items', json={
            'role': 'power_outlet', 'source_uid': sala['sai'],
            'jacks': [{'connector': 'cee-7-3', 'n': 2}, {'connector': 'iec-60320-c13', 'n': 1}]}))
        items = c.get(f'/api/v1/dcim/rooms/{sala["room"]}/items').get_json()['items']
        i = next(x for x in items if x['uid'] == uid)
        assert i['jacks'] == [{'connector': 'cee-7-3', 'n': 2, 'abbr': 'SCH'},
                              {'connector': 'iec-60320-c13', 'n': 1, 'abbr': 'C13'}]
        assert (i['jacks_abbr'], i['source_kind'], i['source_name']) == ('SCH+', 'ups', 'SAI-1')
        # The room's plan reads the same from its features route.
        planta = c.get(f'/api/v1/dcim/rooms/{sala["room"]}/features').get_json()['items']
        assert next(x for x in planta if x['uid'] == uid)['jacks_abbr'] == 'SCH+'

    def test_an_outlet_mixes_copper_fibre_and_video(self, client, admin, sala):
        c = client
        uid = _uid(c.post(f'/api/v1/dcim/rooms/{sala["room"]}/items', json={
            'role': 'outlet', 'jacks': [{'connector': '8p8c', 'n': 2}, {'connector': 'lc-upc', 'n': 1},
                                        {'connector': 'hdmi', 'n': 1}]}))
        guardado = json.loads(admin._dcim_store.items.get(uid)['jacks'])
        assert guardado == [{'connector': '8p8c', 'n': 2}, {'connector': 'lc-upc', 'n': 1},
                            {'connector': 'hdmi', 'n': 1}]

    def test_what_does_not_fit_is_refused(self, client, sala):
        c = client
        base = f'/api/v1/dcim/rooms/{sala["room"]}/items'
        uno = lambda cid, n=1: [{'connector': cid, 'n': n}]           # noqa: E731
        for malo in ({'role': 'power_outlet', 'jacks': uno('8p8c')},
                     {'role': 'outlet', 'jacks': uno('cee-7-3')},
                     {'role': 'outlet', 'jacks': uno('8p8c') + uno('cee-7-3')},
                     {'role': 'power_outlet', 'jacks': uno('cee-7-3', 0)},
                     {'role': 'power_outlet', 'jacks': uno('cee-7-3', -2)},
                     {'role': 'power_outlet', 'jacks': uno('cee-7-3', 2.5)},
                     {'role': 'power_outlet', 'jacks': uno('cee-7-3', 'muchos')},
                     {'role': 'power_outlet', 'jacks': 2},
                     {'role': 'power_outlet', 'jacks': ['cee-7-3']},
                     {'role': 'pc', 'jacks': uno('8p8c')},
                     {'role': 'power_outlet', 'source_uid': sala['ajena']},
                     {'role': 'outlet', 'source_uid': sala['sai']},
                     {'role': 'power_outlet', 'source_uid': 'nope'}):
            assert c.post(base, json=malo).status_code == 400, malo
        uid = _uid(c.post(base, json={'role': 'outlet', 'jacks': uno('lc-upc', 2)}))
        assert c.put(f'/api/v1/dcim/room-items/{uid}', json={'jacks': uno('iec-60320-c13')}).status_code == 400
        assert c.put(f'/api/v1/dcim/room-items/{uid}', json={'jacks': uno('8p8c', 4)}).status_code == 200

    def test_no_maximum_the_same_connector_adds_up_and_empty_is_unsaid(self, client, admin, sala):
        """Asked for: no maximum, only a minimum of 1. Twenty-four is fine; the same connector
        twice is one jack with both counts; emptying the list leaves it unsaid."""
        c = client
        uid = _uid(c.post(f'/api/v1/dcim/rooms/{sala["room"]}/items', json={
            'role': 'outlet', 'jacks': [{'connector': '8p8c', 'n': 24}, {'connector': '8p8c', 'n': '6'}]}))
        assert json.loads(admin._dcim_store.items.get(uid)['jacks']) == [{'connector': '8p8c', 'n': 30}]
        for vacio in (None, [], ''):
            assert c.put(f'/api/v1/dcim/room-items/{uid}', json={'jacks': vacio}).status_code == 200
            assert admin._dcim_store.items.get(uid)['jacks'] == ''

    def test_the_power_view_lists_the_sockets_of_each_source(self, client, sala):
        """Asked for: from a source, see what hangs from it. The sources listing carries, per
        source, its wall sockets with their room and their jacks."""
        c = client
        uid = _uid(c.post(f'/api/v1/dcim/rooms/{sala["room"]}/items', json={
            'role': 'power_outlet', 'label': 'T-01', 'source_uid': sala['sai'],
            'jacks': [{'connector': 'cee-7-3', 'n': 2}]}))
        d = c.get(f'/api/v1/dcim/sources?site={sala["site"]}').get_json()
        assert d['sockets'][sala['sai']] == [{'uid': uid, 'label': 'T-01', 'room': sala['room'],
                                              'room_name': 'Oficina',
                                              'jacks': [{'connector': 'cee-7-3', 'n': 2, 'abbr': 'SCH'}]}]

    def test_deleting_the_source_leaves_it_unsaid(self, client, admin, sala):
        c = client
        uid = _uid(c.post(f'/api/v1/dcim/rooms/{sala["room"]}/items',
                          json={'role': 'power_outlet', 'source_uid': sala['sai']}))
        assert c.delete(f'/api/v1/dcim/sources/{sala["sai"]}').status_code == 200
        assert admin._dcim_store.items.get(uid)['source_uid'] == ''


_PROBE = r"""
__out = {};
_dcriJacks = {connectors: {outlet: [{id: '8p8c', name: 'RJ45 (8P8C)', abbr: 'RJ45'}, {id: 'lc', name: 'LC', abbr: 'LC'},
                                    {id: 'hdmi', name: 'HDMI', abbr: 'HDMI'}],
                           power_outlet: [{id: 'cee-7-3', name: 'CEE 7/3', abbr: 'SCH'},
                                          {id: 'iec-60320-c13', name: 'IEC C13', abbr: 'C13'}]}};
_dcriSources['s1'] = [{uid: 'u1', name: 'SAI-1', kind: 'ups'}, {uid: 'g1', name: 'Grupo', kind: 'generator'}];
_dcimFindRoom = () => ({uid: 'r1', site_uid: 's1'});
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
const toma = {uid: 't1', role: 'power_outlet', room_uid: 'r1', source_uid: 'u1', source_kind: 'ups', box: {},
              jacks: [{connector: 'cee-7-3', n: 2, abbr: 'SCH'}, {connector: 'iec-60320-c13', n: 1, abbr: 'C13'}],
              jacks_abbr: 'SCH+'};
const roseta = {uid: 'o1', role: 'outlet', room_uid: 'r1', box: {}, jacks_abbr: 'RJ45+',
                jacks: [{connector: '8p8c', n: 2, abbr: 'RJ45'}, {connector: 'hdmi', n: 1, abbr: 'HDMI'}]};
__out.lookToma = _dcriItemLook(toma);
__out.lookGrupo = _dcriItemLook(Object.assign({}, toma, {source_kind: 'generator'}));
__out.lookRed = _dcriItemLook(Object.assign({}, toma, {source_kind: 'mains'}));
__out.lookRoseta = _dcriItemLook(roseta);
__out.lookPc = _dcriItemLook({role: 'pc', jacks_abbr: 'X'});
const letra = (svg) => Number((/<text[^>]*font-size="([\d.]+)"/.exec(svg) || [])[1]);
const larga = Object.assign({}, roseta, {jacks_abbr: 'SCHUKO2+', box: {x: 0, y: 0, w: 86, d: 45, rot: 0}});
__out.letrasRoseta = {letra: letra(_dcThingSvg('item', larga, {})), ancho: 86 * _DCP_SCALE,
                      corta: letra(_dcThingSvg('item', Object.assign({}, larga, {jacks_abbr: 'X', box: {x: 0, y: 0, w: 1450, d: 900, rot: 0}}), {}))};
const fichaToma = _dcriPanelHtml(toma, '');
const fichaRoseta = _dcriPanelHtml(roseta, '');
__out.ficha = {
    filasToma: (fichaToma.match(/data-dcri-jack="/g) || []).length,
    conectores: fichaToma.includes('value="cee-7-3" selected') && fichaToma.includes('value="iec-60320-c13" selected'),
    cuantas: /data-dcri-n[^>]*/.test(fichaToma) && /min="1"[^>]*value="2"/.test(fichaToma) && !/max="/.test(fichaToma),
    anadir: fichaToma.includes('data-dcri-jack-add'),
    fuente: fichaToma.includes('data-dcri-source') && fichaToma.includes('value="u1" selected'),
    rosetaSinFuente: fichaRoseta.includes('value="hdmi" selected') && !fichaRoseta.includes('data-dcri-source'),
    rosetaRJ45: fichaRoseta.includes('>RJ45 (8P8C)<'),
    pcSinBoca: !_dcriPanelHtml({uid: 'p1', role: 'pc', room_uid: 'r1', box: {}}, '').includes('data-dcri-jack'),
};
currentUser = {permissions: ['dcim_view']};
const mira = _dcriPanelHtml(toma, '');
__out.miraSinTocar = !mira.includes('data-dcri-jack-add') && !mira.includes('_dcriJackEdit(&quot;t1&quot;,0,&quot;drop')
    && mira.includes('disabled');
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
// Editing the list: add, change and drop, each saving the whole list.
const guardados = [];
_dcObj = (kind, uid) => (uid === 't1' ? toma : null);
_dcriSave = (uid, cambios) => { guardados.push(JSON.parse(JSON.stringify(cambios.jacks))); return Promise.resolve(); };
_dcriJackEdit('t1', -1, 'add');
_dcriJackEdit('t1', 0, 'n', '3');
_dcriJackEdit('t1', 1, 'drop');
__out.edita = guardados;
// The power view: what hangs from a source, strips and wall sockets.
_dcSrc = {hangs: {}, sockets: {u1: [{uid: 't1', label: 'T-01', room: 'r1', room_name: 'Oficina',
                                     jacks: [{connector: 'cee-7-3', n: 2, abbr: 'SCH'}, {connector: 'x', n: 1, abbr: 'C13'}]}]}};
__out.cuelga = _dcSrcHangs('u1', '');
__out.nadaCuelga = _dcSrcHangs('zz', '');
_dcSrc = null;
// The room's list of elements names its room items too: a socket, an outlet.
_dcimPlan = {room: {uid: 'r1', name: 'Oficina', width_mm: 6000, depth_mm: 4000, tile_mm: 600}, racks: []};
_dcpFeat = {features: [], items: [Object.assign({}, toma, {label: 'T-01', box: {x: 600, y: 0, w: 86, d: 45}}),
                                  Object.assign({}, roseta, {label: '', box: {x: 1200, y: 0, w: 86, d: 45}})]};
__out.lista = _dcpElementsHtml();
_dcimPlan = null; _dcpFeat = null;
// The catalogue screen: ticking «outlet jacks» on a connector keeps it ticked.
_dcConnDoc = {families: ['interfaces', 'power-ports', 'power-outlets', 'console-ports', 'console-server-ports',
                         'front-ports', 'rear-ports', 'module-bays', 'device-bays', 'outlet-jacks', 'socket-jacks']};
_dcConnDraftDoc = {connectors: [{id: 'x', families: ['front-ports']}]};
_dcConnDraw = () => {};
_dcConnFamSet(0, 'outlet-jacks', true);
__out.familia = _dcConnDraftDoc.connectors[0].families;
__out.casillas = (_dcConnFamsBox(0, _dcConnDraftDoc.connectors[0], _dcConnDoc.families).match(/<label/g) || []).length;
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
    return node_run(panel_bundle(c), plan2d_catalog_js(c) + _PROBE)


class TestTheDrawingAndTheCard:

    def test_a_socket_says_what_it_hangs_from_and_never_in_red(self, out):
        """A socket fed from a UPS reads «SAI» on orange, from a generator «GE»; from the mains it
        reads its first jack, with a `+` for more kinds. Never red: on this panel red is «down»."""
        assert out['lookToma']['abbr'] in ('SAI', 'UPS') and out['lookToma']['fill'] == '#f97316'
        assert out['lookGrupo']['abbr'] in ('GE', 'GEN') and out['lookGrupo']['fill'] == '#a16207'
        assert out['lookRed']['abbr'] == 'SCH+'
        assert 'red' not in str(out['lookToma']['fill']) and out['lookToma']['fill'] != '#dc3545'

    def test_its_letters_fit_the_drawn_box_however_long(self, out):
        """The abbreviation is not cut in the catalogue: the drawing fits it to the box's width.
        A short one on a big box keeps its usual size."""
        r = out['letrasRoseta']
        assert r['letra'] * 0.6 * len('SCHUKO2+') <= r['ancho'] * 0.9 + 1e-9
        assert r['corta'] > r['letra']

    def test_an_outlet_reads_its_jacks_and_a_pc_its_own_letters(self, out):
        assert out['lookRoseta']['abbr'] == 'RJ45+'
        assert out['lookPc']['abbr'] == 'PC'

    def test_the_card_has_a_row_per_kind_of_jack_and_a_socket_its_source(self, out):
        f = out['ficha']
        assert f['filasToma'] == 2 and f['conectores'] and f['cuantas'] and f['anadir']
        assert f['fuente'] and f['rosetaSinFuente'] and f['rosetaRJ45'] and f['pcSinBoca']

    def test_a_viewer_reads_the_jacks_and_cannot_change_them(self, out):
        assert out['miraSinTocar']

    def test_editing_saves_the_whole_list(self, out):
        """Adding offers a connector not there yet, and when every one is, adds to the usual one
        (a Schuko on a socket) — the same connector twice is one row, summed, as the server keeps
        it; changing a count or dropping a row saves the list as it is left."""
        e = out['edita']
        assert e[0] == [{'connector': 'cee-7-3', 'n': 3}, {'connector': 'iec-60320-c13', 'n': 1}]
        assert e[1][0] == {'connector': 'cee-7-3', 'n': 3}
        assert len(e[2]) == len(e[1]) - 1

    def test_the_rooms_list_names_its_room_items(self, out):
        """Reported: a power socket did not show in the room's list of elements — nor did any
        room item. It does now, by its label or its kind's name, and picking it picks the item."""
        h = out['lista']
        assert 'T-01' in h and ('Roseta' in h or 'Wall outlet' in h)
        assert "_dcpPick(&quot;item&quot;,&quot;t1&quot;)" in h and "_dcpPick(&quot;item&quot;,&quot;o1&quot;)" in h

    def test_the_catalogue_screen_ticks_a_wall_family(self, out):
        """Which connectors are wall jacks is ticked in the catalogue screen. Its boxes were put in
        the order of a device's port families, so ticking a wall one lost it."""
        assert out['familia'] == ['front-ports', 'outlet-jacks']
        assert out['casillas'] == 11

    def test_the_power_view_shows_each_socket_and_opens_its_room(self, out):
        h = out['cuelga']
        assert 'data-dcsrc-socket="t1"' in h and 'T-01' in h and '2×SCH 1×C13' in h and 'Oficina' in h
        assert '_dcSrcGoSocket(' in h
        assert out['nadaCuelga'] == ''
