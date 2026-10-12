#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The DCIM, plan and 3D screens' defects found by the 2026-10-12 audit, pinned in `node`.

A rack opened from the board showed the previous rack's tabs; answers that arrived late were
written into whatever rack, room or site was open by then; a click in the elevation moved an item
one U; undo read its top before flushing what was waiting and could run twice at once; the plan's
keys acted behind a dialog and with the section out of sight; the room's width was lost when
the depth was typed right after; the save buttons sent twice; and the catalogue's import was polled
by a new loop on every search.
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
__out = {};
currentUser = {permissions: ['dcim_view', 'dcim_edit']};
renderDcim = () => {};
_dcRackPrefetch = () => {};
_dcimUrl = () => {};
_dcimMark = () => {};
showToast = () => {};
setTimeout = () => 0;
const tarde = () => { let r; const p = new Promise(ok => { r = ok; }); return [p, r]; };

__wait = (async () => {
    // F3: from the board, rack B forgets rack A's power, cables and history.
    _dcimRack = {rack: {uid: 'A'}, items: []};
    _dcPower = {de: 'A'}; _dcCables = {de: 'A'}; _dcHist = {de: 'A'};
    apiGet = async () => ({rack: {uid: 'B'}, items: []});
    await _dcimBoardGoRack('B');
    __out.tablero = [_dcimRack.rack.uid, _dcPower, _dcCables, _dcHist];

    // F10: open A then B; A answers last and is dropped.
    const [pa, ra] = tarde(), [pb, rb] = tarde();
    apiGet = (url) => url.endsWith('/A') ? pa : pb;
    const la = _dcimLoadRack('A'), lb = _dcimLoadRack('B');
    rb({rack: {uid: 'B'}, items: []}); await lb;
    ra({rack: {uid: 'A'}, items: []}); await la;
    __out.ultimoRack = _dcimRack.rack.uid;

    // F10: a rack's power arriving after another rack was opened is not written into it.
    const [pp, rp] = tarde();
    apiGet = () => pp;
    _dcimRack = {rack: {uid: 'A'}, items: []};
    const pw = _dcPowerOpen();
    _dcimRack = {rack: {uid: 'B'}, items: []};
    rp({de: 'A'}); await pw;
    __out.potencia = _dcPower && _dcPower.de === 'A';

    // F9: a room's pieces land only in the room still open, and a site's contents in its plan.
    _dcpFeat = {de: 'antes'};
    _dcimPlan = {room: {uid: 'B'}};
    apiGet = async () => ({features: [], kinds: {x: 1}});
    p2dEnsureKinds = async () => {};
    await _dcpLoadFeatures('A');
    __out.piezas = _dcpFeat.de;
    const [ps, rs] = tarde();
    apiGet = () => ps;
    const planA = {site: {uid: 'SA'}, kinds: {}, content: {}, walls: {}};
    _dcsPlan = planA;
    const lc = _dcsLoadContents();
    const planB = {site: {uid: 'SB'}, kinds: {}, content: {mio: 1}, walls: {}};
    _dcsPlan = planB;
    rs({rooms: {de: 'SA'}, walls: {}}); await lc;
    __out.sede = [Object.keys(planB.content), Object.keys(planA.content)];

    // F11: width then depth, typed one after the other, are both sent.
    const enviados = [];
    _dcimSend = async (m, u, b) => { enviados.push([m, u, b]); return {ok: true}; };
    _dcpRedraw = () => {};
    _dcpPending = null;
    _dcimPlan = {room: {uid: 'R1', width_mm: 0, depth_mm: 0}};
    _dcpRoomSet('width_mm', '13000');
    _dcpRoomSet('depth_mm', '8000');
    await _dcpFlush();
    __out.medidas = enviados.map(e => e[2]);

    // F6: undo flushes what was waiting FIRST, then takes the top — the flushed step.
    P2DU.stack = [{url: '/viejo', before: {pos_x: 1}, after: {pos_x: 2}, at: 0}];
    P2DU.redo = []; P2DU.running = false; P2DU.busy = false; P2DU.localOnly = false;
    const pedidos = [];
    P2DU.src = {items: () => [], rerender() {}, apply() {},
                send: async (m, u, b) => { pedidos.push(u); return {ok: true}; },
                flush: () => { P2DU.stack.push({url: '/nuevo', before: {pos_x: 5}, after: {pos_x: 6}, at: 0});
                               return Promise.resolve(); }};
    await p2du('undo');
    __out.deshizo = pedidos;

    // F7: two undos at once — the second waits its turn instead of running beside it.
    const [pu, ru] = tarde();
    P2DU.stack = [{url: '/a', before: {}, after: {}, at: 0}, {url: '/b', before: {}, after: {}, at: 0}];
    P2DU.src = {items: () => [], rerender() {}, apply() {}, flush: () => null,
                send: () => pu};
    const u1 = p2du('undo'), u2 = p2du('undo');
    ru({ok: true}); await u1; await u2;
    __out.reentrada = P2DU.stack.length;

    // F19: arrows waiting to be saved are saved now.
    let guardado = null;
    p2dSavePositions = (P, ms) => { guardado = ms.length; return Promise.resolve(); };
    P2D.room.arrowTimer = 7; P2D.room.arrowMoved = [{kind: 'rack', uid: 'x'}];
    await p2dFlushArrows();
    __out.flechas = [guardado, P2D.room.arrowTimer];

    // F8: a plan's keys stay with an open dialog, and with the section out of sight.
    // Ctrl+A answers in a plan — and not with a dialog over it.
    const todo = {key: 'a', ctrlKey: true};
    __out.sinModal = p2dKeyDown(P2D.room, todo);
    document.body.classList.add('modal-open');
    __out.conModal = p2dKeyDown(P2D.room, todo);
    document.body.classList.remove('modal-open');
    const gid = document.getElementById;
    document.getElementById = () => ({offsetParent: null});
    __out.oculto = _dcKeysHere();
    document.getElementById = gid;

    // F4 + F18: a press and a tiny move in the top half of a 2U item does not move it; a
    // cancelled gesture puts it back.
    _dcimRack = {rack: {uid: 'K', u_height: 42}, items: [{uid: 'i1', u_start: 10, u_height: 2}]};
    _dceUAt = (rack, y) => y;                 // one U per unit of y, for the test
    ssCanvasPoint = (id, ev) => ({x: 0, y: ev.y});
    _dceRedraw = () => {};
    const mandados = [];
    _dcimSend = async (m, u, b) => { mandados.push(b); return {ok: true}; };
    const caja = {dataset: {dce: 'i1'}};
    const ev = (y) => ({y, target: {closest: () => caja}, currentTarget: {setPointerCapture() {}}});
    _dceDown(ev(11)); _dceMove(ev(11)); await _dceUp(ev(11));
    __out.clic = [_dcimRack.items[0].u_start, mandados.length];
    _dceDown(ev(11)); _dceMove(ev(14)); _dceCancel();
    __out.cancelado = _dcimRack.items[0].u_start;

    // F5: a save in flight is not sent a second time — two presses while the first waits.
    const [pg, rg] = tarde();
    const altas = [];
    _dcimSend = (m, u, b) => { altas.push(u); return pg; };
    _dcimForm = {mode: 'new', kind: 'site', parent: '', uid: ''};
    const gid2 = document.getElementById;
    document.getElementById = () => ({value: 'Sede X', checked: false});
    const g1 = _dcimSave(), g2 = _dcimSave();
    rg({ok: true, data: {uid: 'n'}});
    await g1; await g2;
    document.getElementById = gid2;
    __out.dobleGuardar = altas.length;

    // F14: one import watcher, however many times the catalogue opens.
    let preguntas = 0;
    apiGet = async () => { preguntas++; return {done: false}; };
    _dcCatJob = 'job1'; _dcCatWatching = false;
    await Promise.all([_dcCatWatch(), _dcCatWatch(), _dcCatWatch()]);
    __out.vigilantes = preguntas;

})();
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
    return node_run(panel_bundle(c), _PROBE)


class TestLateAnswers:

    def test_a_rack_from_the_board_forgets_the_previous_racks_tabs(self, out):
        assert out['tablero'] == ['B', None, None, None]

    def test_the_last_rack_asked_for_is_the_one_open(self, out):
        assert out['ultimoRack'] == 'B'

    def test_a_racks_power_is_not_written_into_another(self, out):
        assert out['potencia'] is False

    def test_a_rooms_pieces_and_a_sites_contents_land_where_they_were_asked(self, out):
        assert out['piezas'] == 'antes'
        assert out['sede'] == [['mio'], []]


class TestEditing:

    def test_width_then_depth_are_both_saved(self, out):
        assert out['medidas'] == [{'width_mm': 13000, 'depth_mm': 8000}]

    def test_undo_flushes_first_and_runs_one_at_a_time(self, out):
        assert out['deshizo'] == ['/nuevo']
        assert out['reentrada'] == 1
        assert out['flechas'] == [1, None]

    def test_keys_stay_with_a_dialog_and_off_screen(self, out):
        assert out['sinModal'] is True
        assert out['conModal'] is False and out['oculto'] is False

    def test_a_click_in_the_elevation_moves_nothing_and_a_cancel_reverts(self, out):
        assert out['clic'] == [10, 0]
        assert out['cancelado'] == 10

    def test_a_save_in_flight_is_not_sent_twice(self, out):
        assert out['dobleGuardar'] == 1

    def test_one_import_watcher(self, out):
        assert out['vigilantes'] == 1
