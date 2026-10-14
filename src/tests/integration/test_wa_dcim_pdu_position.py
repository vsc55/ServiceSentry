#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where each PDU goes in a rack.

Asked for: say where a rack's PDUs are, three ways —

1. a **horizontal** one, 1U (or what it measures), takes its U at the front or the rear like any
   item, and `fits` refuses what would overlap it;
2. two **vertical** ones (0U) in the **same** rear channel, side by side (outer / inner);
3. two vertical ones, **one in each** rear channel.

A vertical one says it with two columns of `dc_item`: `side_pos` (`rear-left` | `rear-right`,
looking at the rack from behind; empty = automatic, the old alternation, so what was written
before renders exactly as before) and `side_slot` (0 outer, 1 inner). The elevation draws them in
their channel beside the rear face (and faded beside the front one), the 3D puts each box in its
channel and the power cords go to the PDU where it is, the horizontal ones included. The demo
shows the three.
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

_needs_node = pytest.mark.skipif(shutil.which(os.environ.get('SS_NODE') or 'node') is None,
                                 reason='no node: nothing to run the script with')


def _uid(r):
    assert r.status_code == 200, r.get_json()
    return r.get_json()['uid']


@pytest.fixture()
def rack(client):
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD',
                                                   'width_mm': 6000, 'depth_mm': 4000}))
    return _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R-01',
                                                   'u_height': 42}))


def _items(client, rack):
    return {i['uid']: i for i in client.get(f'/api/v1/dcim/racks/{rack}').get_json()['items']}


def _side(client, rack, label, **extra):
    return client.post('/api/v1/dcim/items', json=dict(
        {'rack_uid': rack, 'label': label, 'role': 'pdu', 'placement': 'side'}, **extra))


# ── The columns ─────────────────────────────────────────────────────────────────────────────

class TestTheColumns:

    def test_declared_trailing_with_defaults_that_mean_automatic(self):
        from lib.core.dcim.store.items import _ITEM, SIDE_POSITIONS, SIDE_SLOTS
        cols = {c.name: c for c in _ITEM.columns}
        assert cols['side_pos'].type == 'TEXT' and cols['side_pos'].default == "''"
        assert cols['side_slot'].type == 'INTEGER' and cols['side_slot'].default == '0'
        assert SIDE_POSITIONS == ('', 'rear-left', 'rear-right') and SIDE_SLOTS == (0, 1)
        # Before the audit columns, as every column added later: an ADD COLUMN, no migration.
        nombres = [c.name for c in _ITEM.columns]
        assert nombres.index('side_slot') < nombres.index('created_at')

    def test_a_side_item_that_says_nothing_is_automatic(self, client, rack):
        """What was written before these columns reads as automatic: drawn as it always was."""
        uid = _uid(_side(client, rack, 'PDU-A'))
        it = _items(client, rack)[uid]
        assert it['side_pos'] == '' and it['side_slot'] == 0


# ── What the API takes ──────────────────────────────────────────────────────────────────────

class TestTheApi:

    @pytest.mark.parametrize('extra', [{'side_pos': 'top'}, {'side_pos': 'left'},
                                       {'side_pos': ['rear-left']}, {'side_slot': 2},
                                       {'side_slot': -1}, {'side_slot': 'abc'}])
    def test_a_bad_position_or_order_is_a_400_creating(self, client, rack, extra):
        r = _side(client, rack, 'PDU-X', **extra)
        assert r.status_code == 400, r.get_json()
        assert not _items(client, rack)

    @pytest.mark.parametrize('extra', [{'side_pos': 'front-left'}, {'side_slot': 5}])
    def test_and_editing(self, client, rack, extra):
        uid = _uid(_side(client, rack, 'PDU-A', side_pos='rear-left'))
        r = client.put(f'/api/v1/dcim/items/{uid}', json=extra)
        assert r.status_code == 400, r.get_json()
        assert _items(client, rack)[uid]['side_pos'] == 'rear-left'

    def test_round_trip(self, client, rack):
        uid = _uid(_side(client, rack, 'PDU-B', side_pos='rear-right', side_slot=1))
        it = _items(client, rack)[uid]
        assert (it['side_pos'], it['side_slot']) == ('rear-right', 1)
        assert client.put(f'/api/v1/dcim/items/{uid}',
                          json={'side_pos': 'rear-left', 'side_slot': '0'}).status_code == 200
        it = _items(client, rack)[uid]
        assert (it['side_pos'], it['side_slot']) == ('rear-left', 0)

    def test_leaving_the_side_forgets_the_channel(self, client, rack):
        """A channel left written on a PDU bolted to the rails would come back the day it
        returns to the side, without anybody saying so."""
        uid = _uid(_side(client, rack, 'PDU-B', side_pos='rear-right', side_slot=1))
        assert client.put(f'/api/v1/dcim/items/{uid}', json={
            'placement': 'u', 'u_start': 20, 'u_height': 1, 'face': 'rear'}).status_code == 200
        it = _items(client, rack)[uid]
        assert (it['placement'], it['side_pos'], it['side_slot']) == ('u', '', 0)
        # And a channel said to something bolted is not kept either.
        srv = _uid(client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'srv', 'role': 'server', 'u_start': 1, 'u_height': 2,
            'side_pos': 'rear-left'}))
        assert _items(client, rack)[srv]['side_pos'] == ''
        # Nor when it is the only thing an edit says.
        assert client.put(f'/api/v1/dcim/items/{srv}',
                          json={'side_pos': 'rear-right', 'side_slot': 1}).status_code == 200
        assert (_items(client, rack)[srv]['side_pos'], _items(client, rack)[srv]['side_slot'])             == ('', 0)

    def test_the_rack_history_says_the_channel_changed(self, client, rack):
        from lib.core.dcim import rackrev
        assert {'side_pos', 'side_slot'} <= set(rackrev.CAMPOS)
        # A photo from before these columns has no such keys: that is not a change.
        viejo = {'items': [{'uid': 'p', 'label': 'PDU', 'placement': 'side'}]}
        nuevo = {'items': [{'uid': 'p', 'label': 'PDU', 'placement': 'side',
                            'side_pos': '', 'side_slot': 0}]}
        assert rackrev.compare(viejo, nuevo) == []
        movida = {'items': [dict(nuevo['items'][0], side_pos='rear-right')]}
        assert [c['field'] for c in rackrev.compare(nuevo, movida)] == ['side_pos']

    def test_a_foreign_strip_keeps_its_channel(self):
        """Somebody else's strip is drawn where it is, anonymous: its channel is geometry."""
        from lib.core.dcim.owners import opaque
        f = opaque({'uid': 'p', 'label': 'secreto', 'placement': 'side',
                          'side_pos': 'rear-right', 'side_slot': 1})
        assert (f['side_pos'], f['side_slot']) == ('rear-right', 1) and 'label' not in f


class TestAHorizontalPdu:

    def _pdu(self, client, rack, u=10, face='rear'):
        return _uid(client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'PDU-H', 'role': 'pdu', 'placement': 'u',
            'u_start': u, 'u_height': 1, 'face': face}))

    def test_it_takes_its_u_on_its_face(self, client, rack):
        self._pdu(client, rack)
        lleno = client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'srv', 'role': 'server', 'u_start': 10, 'u_height': 1,
            'face': 'full'})
        assert lleno.status_code == 400, 'a server went over the 1U PDU'
        detras = client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'otra', 'role': 'pdu', 'u_start': 10, 'u_height': 1,
            'face': 'rear'})
        assert detras.status_code == 400
        # The front of that U is free: the PDU is at the rear.
        assert client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'panel', 'role': 'patch_panel', 'u_start': 10,
            'u_height': 1, 'face': 'front'}).status_code == 200

    def test_its_outlets_feed_like_a_vertical_ones(self, client, rack):
        item = self._pdu(client, rack)
        pdu = _uid(client.post('/api/v1/dcim/pdus', json={
            'rack_uid': rack, 'item_uid': item, 'name': 'PDU-H', 'feed': 'a', 'outlets': 8}))
        srv = _uid(client.post('/api/v1/dcim/items', json={
            'rack_uid': rack, 'label': 'srv', 'role': 'server', 'u_start': 1, 'u_height': 2}))
        assert client.post('/api/v1/dcim/feeds', json={
            'item_uid': srv, 'pdu_uid': pdu, 'outlet': 3}).status_code == 200
        # An outlet it does not have is refused, as on any strip.
        assert client.post('/api/v1/dcim/feeds', json={
            'item_uid': srv, 'pdu_uid': pdu, 'outlet': 9}).status_code == 400
        pw = client.get(f'/api/v1/dcim/racks/{rack}/power').get_json()
        assert [p['item_uid'] for p in pw['pdus']] == [item]
        suyo = next(i for i in pw['items'] if i['uid'] == srv)
        assert [(f['pdu_uid'], f['outlet']) for f in suyo['feeds']] == [(pdu, 3)]


# ── The screens, run in node ────────────────────────────────────────────────────────────────

_PROBE = r"""
__out = {};
const rack = {uid: 'k', name: 'R01', u_height: 10, width_mm: 600, depth_mm: 1000, desc_units: 0};
const pdu = (uid, extra) => Object.assign({uid, label: uid, role: 'pdu', placement: 'side'}, extra || {});
const casos = {
    auto: [pdu('a1'), pdu('a2')],
    split: [pdu('l', {side_pos: 'rear-left'}), pdu('r', {side_pos: 'rear-right'})],
    // Both on one side, written inner first: the order is the slot, not the list.
    same: [pdu('in', {side_pos: 'rear-right', side_slot: 1}), pdu('out', {side_pos: 'rear-right', side_slot: 0})],
    sameLeft: [pdu('out', {side_pos: 'rear-left', side_slot: 0}), pdu('in', {side_pos: 'rear-left', side_slot: 1})],
    // Two asking for the same place do not overlap.
    clash: [pdu('c1', {side_pos: 'rear-left'}), pdu('c2', {side_pos: 'rear-left'})],
    // An automatic one does not take the place one asked for.
    mixed: [pdu('m1'), pdu('m2', {side_pos: 'rear-left'})],
};
__out.places = {};
for (const [k, items] of Object.entries(casos)) __out.places[k] = _dcimSidePlaces(items);

// ── The elevation ──
const xs = (svg) => {
    const out = {};
    const re = /data-dce="([^"]+)" data-dce-side="(left|right)"[\s\S]*?<rect x="([-\d.]+)"/g;
    let m;
    while ((m = re.exec(svg))) out[m[1]] = {side: m[2], x: Number(m[3])};
    return out;
};
__out.elev = {};
for (const [k, items] of Object.entries(casos)) {
    _dcimRack = {rack, items};
    const svg = _dceContent(rack, items);
    __out.elev[k] = {strips: xs(svg), rearX: _dceFaceX('rear'), W: _DCE.W,
                     front: _dceFace(rack, items, 'front').includes('data-dce-ghost')};
}
_dcimRack = {rack, items: []};
__out.elevEmpty = {rearX: _dceFaceX('rear', _dceContent(rack, [])), noStrip: !_dceContent(rack, []).includes('data-dce-side')};
// Its card says the channel, and the list under the drawing names it too.
_dcimRack = {rack, items: casos.same.concat([{uid: 'ups', label: 'SAI', role: 'ups', placement: 'near'}])};
__out.span = _dceSpan(casos.same[0]);
const debajo = _dceBesideHtml(_dcimRack.items);
__out.beside = ['in', 'out', 'ups'].map(u => debajo.includes(`_dceHover(${jsStr(u)})`));
// A horizontal PDU: in its U, on its face only.
const horiz = [{uid: 'h', label: 'PDU-H', role: 'pdu', placement: 'u', u_start: 5, u_height: 1, face: 'rear'}];
_dcimRack = {rack, items: horiz};
__out.horiz = {rear: _dceFace(rack, horiz, 'rear').includes('data-dce="h"'),
               front: _dceFace(rack, horiz, 'front').includes('data-dce="h"')};

// ── The 3D ──
const caja = (sc, uid) => sc.cajas.find(k => k.lee && k.lee.uid === uid);
__out.d3 = {};
for (const [k, items] of Object.entries(casos)) {
    const sc = _dcr3dScene({rack, items});
    __out.d3[k] = Object.fromEntries(items.map(i => [i.uid, [caja(sc, i.uid).m[12], caja(sc, i.uid).m[14]]]));
}
// Power: to a horizontal PDU at the rear, at the front, and to a vertical one in its channel.
const conLuz = (pduItem) => _dcr3dScene({rack, items: [
    {uid: 'sv', label: 'srv', role: 'server', u_start: 2, u_height: 1, face: 'full', placement: 'u', depth_mm: 600},
    pduItem]}, {energia: true, power: {pdus: [{uid: 'p1', item_uid: pduItem.uid, feed: 'a', outlets: 8, color: '#2f6fed'}],
                                         items: [{uid: 'sv', feeds: [{pdu_uid: 'p1', outlet: 2}]}]}});
const clavija = (sc) => sc.cajas.filter(k => k.cable && Math.abs(k.color[2] - 0xed / 255) < 1e-3).pop();
__out.luz = {};
for (const [k, it] of Object.entries({
        rear: {uid: 'h', label: 'PDU-H', role: 'pdu', placement: 'u', u_start: 8, u_height: 1, face: 'rear'},
        front: {uid: 'h', label: 'PDU-H', role: 'pdu', placement: 'u', u_start: 8, u_height: 1, face: 'front'},
        right: {uid: 'h', label: 'PDU-V', role: 'pdu', placement: 'side', side_pos: 'rear-right'}})) {
    const sc = conLuz(it);
    const b = caja(sc, 'h'), c = clavija(sc);
    __out.luz[k] = {box: [b.m[12], b.m[13], b.m[14], b.m[0], b.m[5], b.m[10]],
                    plug: c ? [c.m[12], c.m[13], c.m[14], c.m[10]] : null};
}

// ── The form ──
const campos = _DCIM_KIND.item.fields;
const f = (n) => campos.find(x => x.name === n);
const pregunta = (n, row) => _dcimAsks(f(n), {mode: 'edit'}, row);
__out.form = {
    sideAsked: [pregunta('side_pos', {placement: 'side'}), pregunta('side_slot', {placement: 'side'})],
    uNotAsked: [pregunta('side_pos', {placement: 'u'}), pregunta('side_slot', {placement: 'near'})],
    choices: f('side_pos').choices, slots: f('side_slot').choices,
    pduWords: _dcimFieldHtml(f('placement'), 0, 'u', 'item', {role: 'pdu'}),
    plainWords: _dcimFieldHtml(f('placement'), 0, 'u', 'item', {role: 'server'}),
    posWords: _dcimFieldHtml(f('side_pos'), 1, '', 'item', {placement: 'side'}),
    roleDrives: !!f('role').drives,
    expect: [t('dcim_place_pdu_u'), t('dcim_place_pdu_side'), t('dcim_place_u'),
             t('dcim_side_pos_'), t('dcim_side_pos_rear-left'), t('dcim_side_pos_rear-right')],
};
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
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


@_needs_node
class TestOneRuleForBothDrawings:

    def test_automatic_alternates_as_before(self, out):
        p = out['places']['auto']
        assert (p['a1']['side'], p['a2']['side']) == ('left', 'right')
        assert p['a1']['auto'] and p['a1']['slot'] == p['a2']['slot'] == 0

    def test_said_one_in_each_channel(self, out):
        p = out['places']['split']
        assert (p['l']['side'], p['r']['side']) == ('left', 'right')
        assert not p['l']['auto']

    def test_both_on_one_side_by_their_order(self, out):
        p = out['places']['same']
        assert p['out'] == {'side': 'right', 'slot': 0, 'auto': False}
        assert p['in'] == {'side': 'right', 'slot': 1, 'auto': False}

    def test_two_asking_the_same_place_do_not_overlap(self, out):
        p = out['places']['clash']
        assert {p['c1']['slot'], p['c2']['slot']} == {0, 1}
        assert p['c1']['side'] == p['c2']['side'] == 'left'

    def test_an_automatic_one_does_not_take_a_said_place(self, out):
        p = out['places']['mixed']
        assert p['m2'] == {'side': 'left', 'slot': 0, 'auto': False}
        assert p['m1']['side'] == 'left' and p['m1']['slot'] == 1


@_needs_node
class TestTheElevation:

    def test_each_in_its_channel_beside_the_rear_face(self, out):
        """The rear face is drawn as seen from behind, so the left of somebody behind the
        rack is the left of the drawing."""
        e = out['elev']['split']
        s = e['strips']
        assert set(s) == {'l', 'r'}
        assert s['l']['side'] == 'left' and s['l']['x'] < e['rearX']
        assert s['r']['side'] == 'right' and s['r']['x'] > e['rearX'] + e['W']
        # And again beside the front, faded: a strip is found from either face.
        assert e['front'], 'the strips are not shown beside the front face'

    def test_automatic_left_then_right(self, out):
        e = out['elev']['auto']
        assert e['strips']['a1']['x'] < e['rearX'] < e['rearX'] + e['W'] < e['strips']['a2']['x']

    def test_two_on_one_side_side_by_side_outer_away_from_the_rail(self, out):
        r = out['elev']['same']
        assert {v['side'] for v in r['strips'].values()} == {'right'}
        assert r['rearX'] + r['W'] < r['strips']['in']['x'] < r['strips']['out']['x']
        lft = out['elev']['sameLeft']
        assert lft['strips']['out']['x'] < lft['strips']['in']['x'] < lft['rearX']

    def test_a_rack_without_them_is_drawn_as_always(self, out):
        """No channel reserved: the same width and the rear face where it always was."""
        assert out['elevEmpty']['noStrip']
        assert out['elevEmpty']['rearX'] == 16 + 300 + 64

    def test_its_card_says_the_channel_and_the_list_below_names_it_too(self, out):
        assert out['beside'] == [True, True, True]
        assert out['span'].count(' · ') == 2

    def test_a_horizontal_one_in_its_u_on_its_face(self, out):
        assert out['horiz'] == {'rear': True, 'front': False}


@_needs_node
class TestThe3d:
    W, POSTE = 0.6, 0.045

    def test_automatic_keeps_the_old_alternation(self, out):
        """The very same x as before these columns: first at the left post, second at the
        right one."""
        d = out['d3']['auto']
        assert d['a1'][0] == pytest.approx(self.POSTE + 0.01)
        assert d['a2'][0] == pytest.approx(self.W - self.POSTE - 0.06)
        assert d['a1'][1] == pytest.approx(1.0 - 0.16) == d['a2'][1]

    def test_said_left_and_right(self, out):
        d = out['d3']['split']
        # Seen from behind (towards -z) the left is the smaller x.
        assert d['l'][0] < self.W / 2 < d['r'][0]

    def test_two_on_one_side_outer_against_the_panel(self, out):
        r = out['d3']['same']
        assert self.W / 2 < r['in'][0] < r['out'][0]
        assert r['out'][0] == pytest.approx(self.W - self.POSTE - 0.06)
        lft = out['d3']['sameLeft']
        assert lft['out'][0] < lft['in'][0] < self.W / 2
        assert lft['out'][0] == pytest.approx(self.POSTE + 0.01)

    def test_a_horizontal_one_is_a_box_in_its_u_at_its_face(self, out):
        rear, front = out['luz']['rear']['box'], out['luz']['front']['box']
        alto_u = 0.04445
        assert rear[1] == pytest.approx(0.08 + 7 * alto_u)            # U8 from the floor
        assert rear[4] < alto_u and rear[3] > 0.4                     # 1U high, rail wide
        assert rear[2] > 0.5 and front[2] < 0.2                       # rear vs front

    def test_the_cord_ends_at_the_pdu_where_it_is(self, out):
        for k in ('rear', 'front'):
            b, p = out['luz'][k]['box'], out['luz'][k]['plug']
            assert p, k
            assert b[0] <= p[0] <= b[0] + b[3], k                     # along the strip
            assert b[1] - 0.01 <= p[1] <= b[1] + b[4], k              # at its U
        # At the rear face of a rear one and the front face of a front one.
        rb, rp = out['luz']['rear']['box'], out['luz']['rear']['plug']
        assert rp[2] <= rb[2] + rb[5] + 0.005 <= rp[2] + rp[3] + 0.001
        fb, fp = out['luz']['front']['box'], out['luz']['front']['plug']
        assert fp[2] <= fb[2] <= fp[2] + fp[3] + 0.005
        # And to a vertical one, in the channel it was put in.
        vb, vp = out['luz']['right']['box'], out['luz']['right']['plug']
        assert vb[0] > self.W / 2 and vb[0] <= vp[0] <= vb[0] + vb[3]


@_needs_node
class TestTheForm:

    def test_the_channel_is_asked_only_of_what_is_on_the_side(self, out):
        fm = out['form']
        assert fm['sideAsked'] == [True, True] and fm['uNotAsked'] == [False, False]
        assert fm['choices'] == ['', 'rear-left', 'rear-right'] and fm['slots'] == ['0', '1']

    def test_a_pdu_is_placed_horizontal_or_vertical(self, out):
        fm = out['form']
        hor, ver, plain, auto, left, right = fm['expect']
        assert hor in fm['pduWords'] and ver in fm['pduWords']
        assert plain in fm['plainWords'] and hor not in fm['plainWords']
        assert fm['roleDrives'], 'choosing the role must redraw the words of the placement'
        assert auto in fm['posWords'] and left in fm['posWords'] and right in fm['posWords']


# ── The demo shows the three ────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def built(tmp_path_factory):
    from lib.core.dcim import demo
    from lib.core.dcim.store import DcimStore
    from lib.db import get_connector
    path = tmp_path_factory.mktemp('pdu-demo')
    store = DcimStore(get_connector(None, default_sqlite_path=str(path / 'data.db')))
    return store, demo.build(store, var_dir=str(path))


def _racks(store, site):
    return {k['name']: k for room in store.rooms_of(site) for k in store.racks_of(room['uid'])}


def _pdu_items(store, rack):
    return sorted((i for i in store.items_of(rack['uid']) if i['role'] == 'pdu'),
                  key=lambda i: i['label'])


class TestTheDemo:

    def test_main_site_one_in_each_rear_channel_said(self, built):
        store, made = built
        racks = _racks(store, made['site'])
        for name in ('A01', 'B03', 'H01'):
            sitios = [(i['placement'], i['side_pos'], i['side_slot'])
                      for i in _pdu_items(store, racks[name])]
            assert sitios == [('side', 'rear-left', 0), ('side', 'rear-right', 0)], name

    def test_the_network_row_both_on_the_left(self, built):
        store, made = built
        racks = _racks(store, made['site'])
        for name in ('N01', 'N02'):
            sitios = [(i['side_pos'], i['side_slot']) for i in _pdu_items(store, racks[name])]
            assert sitios == [('rear-left', 0), ('rear-left', 1)], name

    def test_small_sites_horizontal_at_the_rear_and_every_item_fed_by_both(self, built):
        store, made = built
        for key, esperado in (('site_tx', [('u', 'rear'), ('u', 'rear')]),
                              ('site_dr', [('u', 'rear'), ('side', 'full')])):
            rack = _racks(store, made[key])['R-01']
            pdus = _pdu_items(store, rack)
            assert [(i['placement'], i['face'] if i['placement'] == 'u' else 'full')
                    for i in pdus] == esperado, key
            assert all(i['u_start'] >= 1 and i['u_height'] == 1
                       for i in pdus if i['placement'] == 'u')
            filas = store.pdus_of(rack['uid'])
            assert {p['item_uid'] for p in filas} == {i['uid'] for i in pdus}
            feeds = store.feeds_of([p['uid'] for p in filas])
            activos = [i for i in store.items_of(rack['uid'])
                       if i['role'] in ('router', 'firewall', 'switch', 'server')]
            for it in activos:
                assert len({f['pdu_uid'] for f in feeds if f['item_uid'] == it['uid']}) == 2, \
                    (key, it['label'])

    def test_and_a_front_one_where_the_rack_only_opens_at_the_front(self, built):
        store, made = built
        frente = [i for room in store.rooms_of(made['site'])
                  for k in store.racks_of(room['uid']) for i in store.items_of(k['uid'])
                  if i['role'] == 'pdu' and i['placement'] == 'u' and i['face'] == 'front']
        assert frente, 'no horizontal PDU at the front in the demo'
