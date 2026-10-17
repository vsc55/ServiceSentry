#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The rack form chooses the rack's cabinet model, offers its sizes, and the rack shows it.

Reported: the rack form had no way to say which model of the catalogue a rack is, although the
column (`dc_rack.type_uid`) and its validation existed. Now the form has a model box that
searches the CABINETS (`pickTree: 'rack-types'`; an item's box keeps searching devices); picking
one offers its U, outer width and depth, numbering, post-to-post depth and, for a wall cabinet,
front-only access: empty boxes —and on a new rack the ones still at their starting value— are
filled, and those that already say something else are asked about inside the same dialog. The
rack's header names its model and opens its sheet (the library's drawer, read-only, fetched by
uid); the history names a change of model; the library shows the room equipment's icons.

All in node, over the panel's own bundle.
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


_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
const may = new Set(['dcim_edit', 'dcim_catalog_view', 'dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
let modal = null;
showHtmlModal = (tt, h, v, a) => { modal = {tt, h, a: a || ''}; };
hideInfoModal = () => {};
let toasts = [];
showToast = (m) => { toasts.push(String(m)); };
let cajon = null;
showDrawer = (tt, h, a) => { cajon = {tt, h, a}; };
hideDrawer = () => {};
// The boxes are not in this DOM: the snapshot must keep what the draft holds.
const _g = document.getElementById;
document.getElementById = (id) => String(id).startsWith('dcim-f-') ? null : _g(id);
let pedidas = [];
let responde = () => ({types: []});
apiGet = async (u) => { pedidas.push(u); return responde(u); };

const idx = _DCIM_KIND.rack.fields.findIndex(f => f.name === 'type_uid');
__o.field = Object.assign({}, _DCIM_KIND.rack.fields[idx]);
__o.itemField = Object.assign({}, _DCIM_KIND.item.fields.find(f => f.name === 'type_uid'));

// 1. What a cabinet's sheet says of the rack's boxes.
const ar = {uid: 'm1', tree: 'rack-types', manufacturer: 'Acme', model: 'AR-42', u_tenths: 420,
            extra: {outer_width: 600, outer_depth: 1200, mounting_depth: 1000,
                    desc_units: false, form_factor: '4-post-cabinet', doors: 'perforated'}};
const pulgadas = {tree: 'rack-types', u_tenths: 240,
                  extra: JSON.stringify({outer_width: 23.6, outer_depth: 31.5, outer_unit: 'in'})};
const pared = {uid: 'm2', tree: 'rack-types', manufacturer: 'Acme', model: 'WM-12',
               u_tenths: 120, extra: {outer_width: 600, outer_depth: 450, desc_units: true,
                                      form_factor: 'wall-cabinet'}};
__o.from = {ar: _dcimRackFromModel(ar), inch: _dcimRackFromModel(pulgadas),
            wall: _dcimRackFromModel(pared), none: _dcimRackFromModel({tree: 'rack-types'})};
__o.note = _dcimTypeNote(ar);

// 2. A NEW rack: what is at its starting value is the form's, not the user's — filled.
_dcimForm = {mode: 'new', kind: 'rack', parent: 'room1', uid: '',
             row: {name: 'R', u_height: '42', width_mm: '600', depth_mm: '1000', base_mm: '0',
                   desc_units: '0', rail_front_mm: '', rail_depth_mm: '', rail_rear_mm: '',
                   access: 'front,rear,left,right'}};
_dcimPick = {idx, q: '', rows: [pared]};
_dcimPickTake(idx, 'm2', 'Acme WM-12');
__o.fresh = {row: Object.assign({}, _dcimForm.row), offer: _dcimForm.offer,
             modal: modal && modal.h.includes('dcim-rack-offer'),
             box: modal && modal.h.includes('Acme WM-12')};

// 3. An existing rack whose boxes say other things: asked, in the same dialog.
_dcimForm = {mode: 'edit', kind: 'rack', parent: '', uid: 'r1',
             row: {uid: 'r1', name: 'R', u_height: 42, width_mm: 800, depth_mm: 1000,
                   desc_units: 0, rail_depth_mm: 0, access: 'front,rear'}};
_dcimPick = {idx, q: '', rows: [ar]};
_dcimPickTake(idx, 'm1', 'Acme AR-42');
__o.asked = {row: Object.assign({}, _dcimForm.row),
             offer: JSON.parse(JSON.stringify(_dcimForm.offer)),
             html: modal.h.slice(modal.h.indexOf('dcim-rack-offer') - 40,
                                 modal.h.indexOf('dcim-rack-offer') + 1400)};
_dcimRackOfferTake(true);
__o.taken = {row: Object.assign({}, _dcimForm.row), offer: _dcimForm.offer,
             gone: !modal.h.includes('dcim-rack-offer')};
// …or kept.
_dcimForm = {mode: 'edit', kind: 'rack', parent: '', uid: 'r1',
             row: {uid: 'r1', name: 'R', u_height: 42, width_mm: 800, depth_mm: 1000}};
_dcimPick = {idx, q: '', rows: [ar]};
_dcimPickTake(idx, 'm1', 'Acme AR-42');
_dcimRackOfferTake(false);
__o.kept = {row: Object.assign({}, _dcimForm.row), offer: _dcimForm.offer};
// …and clearing the model leaves nothing to offer.
_dcimForm.offer = {name: 'x', fields: [{campo: 'u_height', ahora: '42', propone: '24'}]};
_dcimPickTake(idx, '', '');
__o.cleared = {type: _dcimForm.row.type_uid, offer: _dcimForm.offer};

// 4. The search looks in the tree the box says.
_dcimPick = {idx, q: '42U', rows: null};
responde = () => ({types: [ar]});
await _dcimPickGo();
__o.searchRack = pedidas[pedidas.length - 1];
__o.searchRows = (_dcimPick.rows || []).length;
_dcimForm = {mode: 'new', kind: 'item', parent: 'r1', uid: '', row: {}};
_dcimPick = {idx: _DCIM_KIND.item.fields.findIndex(f => f.name === 'type_uid'), q: 'x', rows: null};
await _dcimPickGo();
__o.searchItem = pedidas[pedidas.length - 1];

// 5. The header names the model and opens its sheet; a reader without the catalogue sees it.
__o.badge = _dcRackModelBadge({type_uid: 'm1', type_name: 'Acme AR-42'});
__o.badgeNone = _dcRackModelBadge({type_uid: ''});
may.delete('dcim_catalog_view');
__o.badgeReader = _dcRackModelBadge({type_uid: 'm1', type_name: 'Acme AR-42'});
may.add('dcim_catalog_view');
_dcCat = null;
responde = (u) => ({types: u.includes('uid=m1') ? [ar] : []});
await _dcRackModelOpen('m1');
__o.open = {url: pedidas[pedidas.length - 1], title: cajon && cajon.tt,
            actions: cajon && cajon.a, body: cajon && cajon.h};
modal = null;
_dcLibModelFull('m1');
__o.full = {title: modal && modal.tt, actions: modal && modal.a};
cajon = null;
await _dcRackModelOpen('nope');
__o.missing = {drawer: cajon, toast: toasts[toasts.length - 1]};

// 6. The history: an old version without the model is «none», and a change is named.
__o.histOld = _dcRevCompare({name: 'R', items: []}, {name: 'R', type_uid: '', items: []});
__o.histSet = _dcRevCompare({name: 'R', items: []}, {name: 'R', type_uid: 'm1', items: []});
_dcHist = {rows: [], models: {m1: 'Acme AR-42'}};
__o.histOne = _dcHistOne({kind: 'rack', field: 'type_uid', from: '', to: 'm1'});

// 7. The library's «Type»: the room equipment with the plans' icon.
_dcCat = {rows: [], kind_icons: {pc: 'bi-pc-display', ap: 'bi-wifi', bad: 'x" onmouseover="y'}};
__o.icon = {pc: _dcCatKindIcon('pc'), none: _dcCatKindIcon('server'), bad: _dcCatKindIcon('bad')};
__o.cell = _dcCatCell({uid: 'p1', tree: 'device-types', kind: 'pc', model: 'PC-9'}, 'kind');
__o.names = {pc: _dcCatKindName('pc'), phone: _dcCatKindName('phone'),
             ap: _dcCatKindName('ap'), fan: _dcCatKindName('fan')};
})().then(() => {}, (e) => { __o.fallo = String(e && e.stack || e); });
"""


@pytest.fixture(scope='module')
def out():
    """One `node` run for the whole module: starting it costs more than looking."""
    if shutil.which(os.environ.get('SS_NODE') or 'node') is None:
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
    res = node_run(panel_bundle(c), _PROBE)
    assert not res.get('fallo'), res.get('fallo')
    return res


class TestTheModelBox:

    def test_the_rack_searches_cabinets_and_the_item_devices(self, out):
        assert out['field']['pick'] == 'type' and out['field']['pickTree'] == 'rack-types'
        assert out['field']['nameKey'] == 'type_name'
        assert not out['itemField'].get('pickTree')
        assert 'tree=rack-types' in out['searchRack'] and 'q=42U' in out['searchRack']
        assert out['searchRows'] == 1
        assert 'tree=device-types' in out['searchItem']

    def test_what_a_sheet_says_of_the_boxes(self, out):
        assert out['from']['ar'] == {'u_height': '42', 'width_mm': '600', 'depth_mm': '1200',
                                     'desc_units': '0', 'rail_depth_mm': '1000'}
        # Inches are converted; a sheet in a string is read.
        assert out['from']['inch'] == {'u_height': '24', 'width_mm': '599', 'depth_mm': '800'}
        # A wall cabinet: reached from the front only, numbered top-down as its sheet says.
        assert out['from']['wall']['access'] == 'front'
        assert out['from']['wall']['desc_units'] == '1'
        # What the sheet does not say is not invented.
        assert out['from']['none'] == {}
        assert '600 × 1200 mm' in out['note'] and '42 U' in out['note']


class TestTheOffer:

    def test_a_new_rack_takes_them_without_asking(self, out):
        fila = out['fresh']['row']
        assert fila['type_uid'] == 'm2' and fila['type_name'] == 'Acme WM-12'
        assert (fila['u_height'], fila['width_mm'], fila['depth_mm']) == ('12', '600', '450')
        assert fila['access'] == 'front' and fila['desc_units'] == '1'
        assert out['fresh']['offer'] is None and not out['fresh']['modal']
        assert out['fresh']['box'], 'the box does not show the chosen model'

    def test_an_existing_rack_is_asked_and_its_empty_boxes_filled(self, out):
        a = out['asked']
        # Empty (0 = nobody measured): filled. Different: asked, nothing overwritten yet.
        assert a['row']['rail_depth_mm'] == '1000'
        assert (a['row']['u_height'], a['row']['width_mm']) == (42, 800)
        campos = {x['campo']: (x['ahora'], x['propone']) for x in a['offer']['fields']}
        assert campos == {'width_mm': ('800', '600'), 'depth_mm': ('1000', '1200')}
        assert a['offer']['name'] == 'Acme AR-42'
        assert '_dcimRackOfferTake(true)' in a['html'] and '_dcimRackOfferTake(false)' in a['html']
        assert '800' in a['html'] and '1200' in a['html']
        # u_height says the same (42), so it is not asked.
        assert 'u_height' not in campos

    def test_taking_writes_them_and_keeping_does_not(self, out):
        assert out['taken']['row']['width_mm'] == '600' and out['taken']['row']['depth_mm'] == '1200'
        assert out['taken']['offer'] is None and out['taken']['gone']
        assert out['kept']['row']['width_mm'] == 800 and out['kept']['row']['depth_mm'] == 1000
        assert out['kept']['offer'] is None
        assert out['cleared'] == {'type': '', 'offer': None}


class TestTheHeader:

    def test_it_names_the_model_and_opens_it(self, out):
        assert 'data-dc-rack-model="m1"' in out['badge'] and 'Acme AR-42' in out['badge']
        assert '_dcRackModelOpen(&quot;m1&quot;)' in out['badge']
        assert out['badgeNone'] == ''
        assert 'Acme AR-42' in out['badgeReader'] and '_dcRackModelOpen' not in out['badgeReader']

    def test_the_sheet_is_fetched_by_uid_and_only_looked_at(self, out):
        o = out['open']
        assert 'tree=rack-types' in o['url'] and 'uid=m1' in o['url']
        assert o['title'] == 'Acme AR-42'
        assert '_dcLibModelFull(' in o['actions']
        # Even with the catalogue's management permission: editing is the library's.
        assert '_dcLibModelEdit' not in o['actions'] and '_dcLibModelDrop' not in o['actions']
        assert out['full']['title'] == 'Acme AR-42' and out['full']['actions'] == ''
        assert out['missing']['drawer'] is None and out['missing']['toast']


class TestTheHistory:

    def test_an_old_version_is_none_and_a_change_is_named(self, out):
        assert out['histOld'] == []
        assert out['histSet'] == [{'kind': 'rack', 'field': 'type_uid', 'from': '', 'to': 'm1'}]
        assert 'Acme AR-42' in out['histOne'] and 'm1' not in out['histOne'].replace('Acme', '')


class TestTheLibraryType:

    def test_the_room_equipment_with_its_icon(self, out):
        assert 'bi-pc-display' in out['icon']['pc']
        assert out['icon']['none'] == '' and out['icon']['bad'] == ''
        assert 'bi-pc-display' in out['cell']
        for k, v in out['names'].items():
            assert v and not v.startswith(('dcim_', 'plan2d_')), (k, v)
