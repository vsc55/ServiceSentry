#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A rack's elevation and its power strips, as a browser check found them.

A. **A lost click after closing a form.** `_dcimOpen` toggles, and closing the dialog by its X,
   «Cerrar» or Esc did not forget the form: the next click on the same thing did nothing.
B. **Nothing in a U opened with a click** in the elevation: `_dceDown` captured the pointer at
   pointerdown, and Chromium then sends the `click`/`dblclick` to the `<svg>`, not the item.
   The capture now waits for a real drag; and a click waits a moment for a second one, or the
   form's dialog covered the drawing before the double click (the parts) could arrive.
C. **A strip's own settings could not be edited anywhere**: its row only had colour, source,
   device and delete. A form now edits all of it, from the row and from the item that IS the
   strip; fewer outlets than are in use is refused by the server.
D. **0U strips nearly invisible**: an 11 px outline in the device's state colour, only beside
   the rear face. Now in their strip's branch colour, wider, and faded beside the front too.
E. **0U strips listed again** under the elevation, with what takes no U.
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


# ── The server: the strip's route ───────────────────────────────────────────────────────────

@pytest.fixture()
def strip(client):
    """A rack with a strip of 24 outlets and two servers plugged into outlets 3 and 7."""
    _login(client)
    c = client
    site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'Sede'}))
    room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'CPD',
                                                   'width_mm': 6000, 'depth_mm': 4000}))
    rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R-01',
                                                   'u_height': 42}))
    item = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': 'PDU-V',
                                                   'role': 'pdu', 'placement': 'side'}))
    pdu = _uid(c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'item_uid': item,
                                                 'name': 'PDU-A', 'feed': 'a', 'outlets': 24}))
    for n, toma in ((1, 3), (3, 7)):
        srv = _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'label': f'srv{n}',
                                                      'role': 'server', 'u_start': n,
                                                      'u_height': 1}))
        assert c.post('/api/v1/dcim/feeds', json={'item_uid': srv, 'pdu_uid': pdu,
                                                  'outlet': toma}).status_code == 200
    return {'rack': rack, 'pdu': pdu, 'item': item}


def _row(client, s):
    pw = client.get(f"/api/v1/dcim/racks/{s['rack']}/power").get_json()
    return next(p for p in pw['pdus'] if p['uid'] == s['pdu'])


class TestTheStripsRoute:

    def test_every_field_of_the_form_is_saved(self, client, strip):
        r = client.put(f"/api/v1/dcim/pdus/{strip['pdu']}", json={
            'name': 'PDU-B2', 'feed': 'b', 'outlets': 12, 'capacity_w': 3600,
            'description': 'lado derecho', 'color': '#123456', 'source_uid': ''})
        assert r.status_code == 200, r.get_json()
        p = _row(client, strip)
        assert (p['name'], p['feed'], p['outlets'], p['capacity_w']) == ('PDU-B2', 'b', 12, 3600)
        # What the form needs and the list did not carry: the description, and the colour
        # as written —a colour of its own— apart from the one resolved for drawing.
        assert p['description'] == 'lado derecho'
        assert p['color_own'] == '#123456' == p['color']

    def test_an_empty_colour_is_the_branchs(self, client, strip):
        assert client.put(f"/api/v1/dcim/pdus/{strip['pdu']}",
                          json={'color': '', 'feed': 'b'}).status_code == 200
        p = _row(client, strip)
        assert p['color_own'] == ''
        from lib.core.dcim.store import FEED_COLORS
        assert p['color'] == FEED_COLORS['b']

    def test_fewer_outlets_than_the_highest_in_use_is_refused(self, client, strip):
        r = client.put(f"/api/v1/dcim/pdus/{strip['pdu']}", json={'outlets': 5})
        assert r.status_code == 400
        assert '7' in r.get_json()['error'] and '5' in r.get_json()['error']
        assert _row(client, strip)['outlets'] == 24

    def test_unnumbered_leads_count_without_raising_the_floor(self, client, strip):
        """Leads in «not sure which» (outlet 0) take an outlet each, but five leads with the
        highest in 7 still fit in seven."""
        rack = strip['rack']
        for n in range(3):
            srv = _uid(client.post('/api/v1/dcim/items', json={
                'rack_uid': rack, 'label': f'x{n}', 'role': 'server', 'u_start': 10 + n,
                'u_height': 1}))
            assert client.post('/api/v1/dcim/feeds', json={
                'item_uid': srv, 'pdu_uid': strip['pdu'], 'outlet': 0}).status_code == 200
        assert client.put(f"/api/v1/dcim/pdus/{strip['pdu']}",
                          json={'outlets': 7}).status_code == 200
        assert _row(client, strip)['outlets'] == 7

    def test_down_to_exactly_what_is_used_and_zero_pass(self, client, strip):
        assert client.put(f"/api/v1/dcim/pdus/{strip['pdu']}",
                          json={'outlets': 7}).status_code == 200
        # 0 is «nobody said how many»: no outlet falls outside a count that does not exist.
        assert client.put(f"/api/v1/dcim/pdus/{strip['pdu']}",
                          json={'outlets': 0}).status_code == 200

    def test_more_leads_than_outlets_without_numbers(self, client):
        _login(client)
        c = client
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': 'S'}))
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'C',
                                                       'width_mm': 3000, 'depth_mm': 3000}))
        rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'R',
                                                       'u_height': 12}))
        pdu = _uid(c.post('/api/v1/dcim/pdus', json={'rack_uid': rack, 'name': 'P',
                                                     'feed': 'a', 'outlets': 8}))
        for n in range(3):
            srv = _uid(c.post('/api/v1/dcim/items', json={
                'rack_uid': rack, 'label': f's{n}', 'role': 'server', 'u_start': n + 1,
                'u_height': 1}))
            assert c.post('/api/v1/dcim/feeds', json={'item_uid': srv, 'pdu_uid': pdu,
                                                      'outlet': 0}).status_code == 200
        r = c.put(f'/api/v1/dcim/pdus/{pdu}', json={'outlets': 2})
        assert r.status_code == 400 and '3' in r.get_json()['error']
        assert c.put(f'/api/v1/dcim/pdus/{pdu}', json={'outlets': 3}).status_code == 200


# ── The screens, run in node ────────────────────────────────────────────────────────────────

_PROBE = r"""
__out = {};
(async () => {
const rack = {uid: 'K', name: 'R01', u_height: 10, width_mm: 600, depth_mm: 1000, desc_units: 0};
const items = [
    {uid: 'v1', label: 'PDU-A', role: 'pdu', placement: 'side', side_pos: 'rear-left',
     device_uid: 'd1', state: 'down'},
    {uid: 'v2', label: 'PDU-X', role: 'pdu', placement: 'side', side_pos: 'rear-right'},
    {uid: 's1', label: 'srv', role: 'server', placement: 'u', u_start: 4, u_height: 2, face: 'full'},
];
_dcimRack = {rack, items};
_dcimMay = () => true;
_dcPower = {pdus: [{uid: 'p1', name: 'PDU-A', feed: 'a', outlets: 24, used: 2,
                    outlets_used: [3, 7], free: 22, capacity_w: 3000, color: '#2f6fed',
                    color_own: '', description: 'izq', source_uid: '', item_uid: 'v1'}],
            feed_kinds: ['a', 'b', 'none'], sources: [], items: []};

// ── A: closing the dialog forgets the form ──
// The bundle hooks itself when it loads: nobody has to remember to call it.
const alCargar = !!window._dcimFormHideHooked;
let oyente = null;
const add = document.addEventListener;
document.addEventListener = (tipo, fn) => { if (tipo === 'hidden.bs.modal') oyente = fn; };
window._dcimFormHideHooked = false;
_dcimFormHook();
document.addEventListener = add;
const dibujar = _dcimFormDraw;
_dcimFormDraw = () => {};
_dcimForm = null;
_dcimOpen('edit', 'item', '', 's1');
const abierto = !!_dcimForm;
if (oyente) oyente({target: {id: 'infoModal'}});
const olvidado = _dcimForm === null;
_dcimOpen('edit', 'item', '', 's1');
const otraVez = !!_dcimForm;
// Another dialog closing is not this one.
if (oyente) oyente({target: {id: 'otroModal'}});
__out.a = {abierto, olvidado, otraVez, sigue: !!_dcimForm, hooked: !!oyente, alCargar};
_dcimFormDraw = dibujar;
_dcimForm = null;

// ── B: no capture until it is a drag ──
const capturas = [];
const svg = {setPointerCapture: (id) => capturas.push(id)};
const caja = {dataset: {dce: 's1'}};
const ev = (x, y) => ({clientX: x, clientY: y, pointerId: 7,
                       target: {closest: () => caja}, currentTarget: svg});
ssCanvasPoint = (id, e) => ({x: e.clientX, y: e.clientY});
_dceRedraw = () => {};
_dceDown(ev(100, 120));
const alPulsar = capturas.length;
_dceMove(ev(101, 121));
const temblor = capturas.length;
_dceMove(ev(100, 124));
const arrastre = capturas.slice();
_dceMove(ev(100, 160));
__out.b = {alPulsar, temblor, arrastre, unaVez: capturas.length};
_dceCancel();
_dcimRack.items[2].u_start = 4;

// ── B2: a click waits for a possible second one; a double click opens the parts only ──
const abiertos = [], partes = [];
const abrir = _dcimOpen, piezas = _dcPartsOpen;
_dcimOpen = (m, k, p, u) => abiertos.push(u);
_dcPartsOpen = (u) => partes.push(u);
// The harness's timers do nothing: these keep what is pending, and `espera` lets it run out.
const pend = new Map();
let nT = 0;
const ponT = setTimeout, quitaT = clearTimeout;
setTimeout = (fn, ms) => { pend.set(++nT, [fn, ms]); return nT; };
clearTimeout = (id) => { pend.delete(id); };
const espera = async () => {
    const vencen = [...pend.values()];
    pend.clear();
    vencen.forEach(([fn, ms]) => { if (ms <= _DCE_DBL_MS) fn(); });
};
_dceClick({detail: 1}, 's1');
const alInstante = abiertos.length;
await espera();
const luego = abiertos.slice();
_dceClick({detail: 1}, 's1');
_dceClick({detail: 2}, 's1');
_dceDbl('s1');
await espera();
_dcimOpen = abrir;
_dcPartsOpen = piezas;
setTimeout = ponT;
clearTimeout = quitaT;
_dceContent(rack, items);
const cajaS1 = (_dceFace(rack, items, 'front').match(/<g class="ss-pointer" data-dce="s1"[^>]*>/) || [''])[0];
__out.b2 = {alInstante, luego, doble: abiertos.slice(luego.length), partes,
            click: cajaS1.includes('_dceClick(event,'), dbl: cajaS1.includes('_dceDbl(')};

// ── C: the strip's form ──
let modal = null;
const showHtml = showHtmlModal;
showHtmlModal = (title, html, variant, actions) => { modal = {title, html, actions}; };
await _dcPduEdit('p1');
const h = (modal || {}).html || '';
__out.c = {
    title: (modal || {}).title || '',
    ids: ['dcpe-name', 'dcpe-feed', 'dcpe-outlets', 'dcpe-cap', 'dcpe-color', 'dcpe-colorb',
          'dcpe-src', 'dcpe-desc'].map(i => h.includes(`id="${i}"`)),
    ramas: ['a', 'b', 'none'].map(f => h.includes(`<option value="${f}"`)),
    minimo: h.includes('min="7"'),
    colorDeRama: /id="dcpe-colorb"[^>]*checked/.test(h),
    abrirEquipo: h.includes(`_dcPduOpenItem(${jsStr('v1')})`),
    guardar: ((modal || {}).actions || '').includes('_dcPduEditSave()'),
    abierta: _dcPduEd,
};
const valores = {'dcpe-name': ' PDU-B ', 'dcpe-feed': 'b', 'dcpe-outlets': '12',
                 'dcpe-cap': '3600', 'dcpe-color': '#ff0000', 'dcpe-src': '',
                 'dcpe-desc': 'derecha'};
const gid = document.getElementById;
document.getElementById = (id) => ({value: valores[id], checked: id === 'dcpe-colorb'});
const mandados = [];
const toasts = [];
showToast = (m, k) => toasts.push([m, k]);
_dcPowerOpen = async () => {};
_dcimSend = async (m, u, b) => { mandados.push([m, u, b]); return {ok: false, error: 'NO'}; };
await _dcPduEditSave();
__out.c.rechazo = {sigue: _dcPduEd, toast: toasts.slice()};
_dcimSend = async (m, u, b) => { mandados.push([m, u, b]); return {ok: true}; };
await _dcPduEditSave();
document.getElementById = gid;
__out.c.mandados = mandados;
__out.c.cerrada = _dcPduEd;
// From the strip's row, a solid pencil.
__out.c.fila = _dcPduRow(Object.assign({load: null, watts_said: 0}, _dcPower.pdus[0]));
// The item's form says it IS a strip — only when it is one.
__out.c.bloque = [_dcPduItemBlock('v1'), _dcPduItemBlock('s1'), _dcPduItemBlock('v2')];
_dcimForm = {mode: 'edit', kind: 'item', parent: '', uid: 'v1', row: items[0]};
const cuerpoV1 = _dcimFormBody();
_dcimForm = {mode: 'edit', kind: 'item', parent: '', uid: 's1', row: items[2]};
const cuerpoS1 = _dcimFormBody();
_dcimForm = null;
__out.c.formulario = [cuerpoV1.includes('data-dc-pdu-block'), cuerpoS1.includes('data-dc-pdu-block'),
                      cuerpoV1.includes(`_dcPduEdit(${jsStr('p1')})`)];
showHtmlModal = showHtml;

// ── D: the strips, in their colour, beside both faces ──
const gs = (svgTxt) => {
    const out = [];
    const re = /<g class="ss-pointer" data-dce="([^"]+)"([^>]*)>[\s\S]*?<rect x="([-\d.]+)"[^>]*?width="([\d.]+)"[^>]*?fill="([^"]+)"[^>]*?stroke="([^"]+)"/g;
    let m;
    while ((m = re.exec(svgTxt))) out.push({uid: m[1], ghost: m[2].includes('data-dce-ghost'),
        click: m[2].includes('_dcimOpen('), x: Number(m[3]), w: Number(m[4]),
        fill: m[5], stroke: m[6]});
    return out;
};
_dceContent(rack, items);                   // sets the channels' width, as the drawing does
const frente = gs(_dceFace(rack, items, 'front'));
const atras = gs(_dceFace(rack, items, 'rear'));
__out.d = {frente, atras, frontX: _dceFaceX('front'), rearX: _dceFaceX('rear'), W: _DCE.W,
           width: _dceWidth(), sw: _DCE_SW};

// ── E: listed under the drawing ──
const debajo = _dceBesideHtml(items);
__out.e = ['v1', 'v2', 's1'].map(u => debajo.includes(`_dcimOpen('edit','item','',${jsStr(u)})`));
})().then(() => {}, (e) => { __out.fallo = String(e && e.stack || e); });
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
    # The probe is async (the strip's form awaits); `__wait` makes the harness wait for it.
    probe = _PROBE.replace('(async () => {', '__wait = (async () => {', 1)
    res = node_run(panel_bundle(c), probe)
    assert not res.get('fallo'), res.get('fallo')
    return res


@_needs_node
class TestAClosedDialogForgetsTheForm:

    def test_closing_by_the_dialog_and_clicking_again_opens_at_once(self, out):
        a = out['a']
        assert a['alCargar'], 'loading the panel does not hook the dialog closing'
        assert a['hooked'], 'nothing listens for the dialog closing'
        assert a['abierto'] and a['olvidado'], 'closing the dialog left the form behind'
        assert a['otraVez'], 'the first click after closing did nothing'

    def test_another_dialog_closing_does_not_touch_it(self, out):
        assert out['a']['sigue']


@_needs_node
class TestAClickReachesTheItem:

    def test_no_capture_on_press_nor_on_a_tremble(self, out):
        """Capturing at pointerdown sends the click to the <svg>: the item's onclick never
        runs. A 1 px tremble during a click is not a drag either."""
        assert out['b']['alPulsar'] == 0
        assert out['b']['temblor'] == 0

    def test_a_real_drag_captures_once(self, out):
        assert out['b']['arrastre'] == [7]
        assert out['b']['unaVez'] == 1

    def test_a_click_opens_the_form_after_waiting_for_a_second_one(self, out):
        """The form's dialog, opened at once, covered the drawing before the second click of a
        double click arrived: the parts never opened. The click now waits a moment."""
        b2 = out['b2']
        assert b2['click'] and b2['dbl'], 'the box is not wired to the click/double click pair'
        assert b2['alInstante'] == 0 and b2['luego'] == ['s1']

    def test_a_double_click_opens_the_parts_and_not_the_form(self, out):
        assert out['b2']['partes'] == ['s1']
        assert out['b2']['doble'] == [], 'a double click also opened the form'


@_needs_node
class TestTheStripsForm:

    def test_it_has_every_field(self, out):
        c = out['c']
        assert all(c['ids']), c['ids']
        assert all(c['ramas']), 'the branches are not the server\'s'
        assert c['minimo'], 'the outlets do not say their floor'
        assert c['colorDeRama'], 'a strip without a colour of its own is not «branch colour»'
        assert c['abrirEquipo'] and c['guardar'] and c['abierta'] == 'p1'
        assert 'PDU-A' in c['title']

    def test_it_saves_through_the_strips_route(self, out):
        m, u, b = out['c']['mandados'][-1]
        assert (m, u) == ('PUT', '/api/v1/dcim/pdus/p1')
        assert b == {'name': 'PDU-B', 'feed': 'b', 'outlets': 12, 'capacity_w': 3600,
                     'source_uid': '', 'description': 'derecha', 'color': ''}
        assert out['c']['cerrada'] == ''

    def test_a_refusal_keeps_the_form_and_says_why(self, out):
        r = out['c']['rechazo']
        assert r['sigue'] == 'p1'
        assert r['toast'] == [['NO', 'danger']]

    def test_its_row_has_a_solid_pencil(self, out):
        fila = out['c']['fila']
        assert '_dcPduEdit(' in fila and 'bi-pencil' in fila
        assert 'btn-outline' not in fila

    def test_the_items_form_shows_the_strip_only_when_it_is_one(self, out):
        v1, s1, v2 = out['c']['bloque']
        assert 'data-dc-pdu-block' in v1 and '_dcPduEdit(' in v1 and 'PDU-A' in v1
        assert s1 == '' and v2 == ''
        assert out['c']['formulario'] == [True, False, True]


@_needs_node
class TestTheStripsInTheElevation:

    def test_in_their_strips_colour_not_the_state(self, out):
        atras = {g['uid']: g for g in out['d']['atras']}
        assert set(atras) >= {'v1', 'v2'}
        assert atras['v1']['fill'] == atras['v1']['stroke'] == '#2f6fed', \
            'a strip is drawn in its device state and not its branch'
        # Not declared as a strip: the colour of «no branch», not nothing.
        assert atras['v2']['stroke'] == '#6c757d'
        assert not atras['v1']['ghost']

    def test_wider_than_before(self, out):
        assert out['d']['sw'] >= 14
        assert all(g['w'] == out['d']['sw'] for g in out['d']['atras'] if g['uid'] != 's1')

    def test_beside_the_front_too_faded_mirrored_and_clickable(self, out):
        d = out['d']
        frente = {g['uid']: g for g in d['frente'] if g['ghost']}
        assert set(frente) == {'v1', 'v2'}, 'the strips are not shown beside the front face'
        assert all(g['click'] for g in frente.values())
        # The rear's left channel is the front's right.
        assert frente['v1']['x'] > d['frontX'] + d['W']
        assert frente['v2']['x'] < d['frontX']
        assert frente['v1']['stroke'] == '#2f6fed'

    def test_everything_inside_the_drawing_and_apart(self, out):
        d = out['d']
        xs = [g['x'] for g in d['frente'] + d['atras'] if g['uid'] != 's1']
        assert min(xs) >= 0 and max(xs) + d['sw'] <= d['width']
        # The front's right channel does not run into the rear's left one.
        frente_der = max(g['x'] for g in d['frente'] if g['ghost']) + d['sw']
        atras_izq = min(g['x'] for g in d['atras'] if g['uid'] != 's1')
        assert frente_der < atras_izq


@_needs_node
class TestTheListUnderTheElevation:

    def test_0u_strips_are_listed_and_what_takes_a_u_is_not(self, out):
        assert out['e'] == [True, True, False]
