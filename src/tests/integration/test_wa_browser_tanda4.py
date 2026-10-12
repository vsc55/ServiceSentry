#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The fourth batch of the 2026-10-12 audit's browser defects, pinned in `node`.

A cable or power form lost what was typed when the section repainted; the rack's 3D kept its
WebGL context and its refresh after leaving DCIM; a cloned power source always said 0 rows; the
file list of a catalogue model did not refresh; a failed cut retried into a second leg; a socket
clicked twice plugged a cable in twice; a model's picture landed in the model opened meanwhile;
a rack opened in one room's 3D landed in the next; a search answered into a viewer already let
go; the 3D image cache never let go; a camera from the address could sit inside its target. And
outside DCIM: "Reset to factory" always looked failed, an overview table kept the previous
filter's rows, one missed poll gave a collection up for lost, `/status` folded what the reader
had opened on every refresh, and the asset version only followed one stylesheet.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import time

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
currentUser = {permissions: ['dcim_view', 'dcim_edit', 'dcim_cable_edit', 'infra_collect']};
const avisos = [];
showToast = (m, k) => { avisos.push([String(m), k]); };
setTimeout = () => 0;
const tarde = () => { let r; const p = new Promise(ok => { r = ok; }); return [p, r]; };
const vacia = async () => { for (let i = 0; i < 30; i++) await null; };

__wait = (async () => {
    // U4: «Restablecer de fábrica» reads the server's `ok` from `data`.
    const fabrica = [{id: 'w1'}];
    _dwBuiltinLayout = () => fabrica;
    _dwKey = () => 'k';
    renderOverview = () => {};
    let sucio = null;
    _dwMarkDirty = (v) => { sucio = v; };
    apiPost = async () => ({status: 200, data: {ok: true}});
    currentUser.dashboard_layout = null;
    await _dwResetFactory();
    __out.fabrica = [currentUser.dashboard_layout === fabrica, sucio];

    // U5: a table asked again while a request is in flight shows the NEW filter's rows.
    const dw = {dataset: {f: 'a'}, style: {display: ''}, querySelector: () => ({innerHTML: ''})};
    const qs = document.querySelector;
    document.querySelector = () => dw;
    _DW_DEFS['tt'] = {view: {kind: 'table', data_url: '/x', columns: [],
                             filter: {store: 'f', param: 'f'}}};
    const pedidas = [], respuestas = [];
    apiGet = (url) => { pedidas.push(url); const [p, r] = tarde(); respuestas.push(r); return p; };
    const t1 = _dwTableFetch('tt');
    dw.dataset.f = 'b';
    _dwTableFetch('tt');
    respuestas[0]({rows: [{de: 'a'}]});
    await t1; await vacia();
    if (respuestas[1]) respuestas[1]({rows: [{de: 'b'}]});
    await vacia();
    __out.tabla = [pedidas, (_dwTableRows['tt'] || []).map(r => r.de)];
    document.querySelector = qs;

    // U8: one unanswered poll does not give the collection up; a run of them does.
    setTimeout = (f) => { f(); return 0; };
    _infraCollectPaint = () => {};
    let fin = null;
    _infraCollectFinish = (j) => { fin = j.id; };
    let n = 0;
    apiGet = async () => (++n === 1 ? null : {id: 'J', done: true});
    avisos.length = 0;
    await _infraCollectPoll('J');
    __out.sondeo = [fin, avisos.length];
    fin = null;
    apiGet = async () => null;
    await _infraCollectPoll('K');
    __out.perdido = [fin, avisos.length];
    setTimeout = () => 0;

    // F13: what was typed in a form marked to keep survives the repaint.
    const campo = (id, v, mas) => Object.assign({id, value: v, type: 'text', tagName: 'INPUT',
                                                 disabled: false}, mas || {});
    let campos = [campo('dcc-ap', '24'), campo('dcc-m', '1,5'),
                  campo('dcni-p-0', 'on', {type: 'checkbox', checked: false})];
    const pane = {querySelectorAll: () => campos};
    const g = _dcKeepTake(pane);
    campos = [campo('dcc-ap', ''), campo('dcc-m', ''),
              campo('dcni-p-0', 'on', {type: 'checkbox', checked: true})];
    _dcKeepPut(pane, g);
    __out.guardado = campos.map(c => c.type === 'checkbox' ? c.checked : c.value);
    _dcNewCable = true; _dcNewItem = true;
    _dcimRack = {rack: {uid: 'R'}, items: [{uid: 'i1'}]};
    __out.marcas = [/data-dc-keep/.test(_dcCableFormHtml()),
                    /data-dc-keep/.test(_dcPowerNewItem([{uid: 'p', color: '#000', free: 1, name: 'P'}])),
                    /_dcKeepRepaint\(/.test(String(renderDcim))
                        && /_dcKeepTake\(/.test(String(_dcKeepRepaint))
                        && /_dcKeepPut\(/.test(String(_dcKeepRepaint))];
    _dcNewCable = false; _dcNewItem = false;

    // F17: leaving DCIM lets the rack viewer go, and the refresh skips a viewer out of sight.
    const parados = [];
    ss3dStop = (id) => parados.push(id);
    ss3dGet = (id) => (id === _DCR3D_BOX ? {} : null);
    _dcr3dLeave({target: {getAttribute: () => '#tab-infra'}});
    _dcr3dLeave({target: {getAttribute: () => '#tab-dcim'}});
    __out.salir = parados;
    let vivas = 0;
    apiGet = async () => { vivas++; return null; };
    ss3dRebuild = () => {};
    const gid = document.getElementById;
    document.getElementById = () => ({getClientRects: () => []});
    await _dc3dLiveTick();
    const oculto = vivas;
    document.getElementById = () => ({getClientRects: () => [1]});
    await _dc3dLiveTick();
    __out.vivo = [oculto, vivas];
    document.getElementById = gid;

    // F20: the clone says how many rows it wrote.
    let pend = null;
    showConfirmModal = (m, fn) => { pend = fn(); };
    _dcimSend = async () => ({ok: true, data: {uid: 'n', n: 7}});
    _dcSrcOpen = () => {};
    _dcSrc = {sources: []};
    avisos.length = 0;
    _dcSrcClone('s1', 'X');
    await pend;
    __out.clon = avisos.map(a => a[0]);

    // F20: a file dropped from a catalogue model repaints the model, not the section.
    let mio = 0, seccion = 0;
    const rd = renderDcim;
    renderDcim = () => { seccion++; };
    apiGet = async () => ({files: [], kinds: []});
    await _dcFilesLoad('type', 'u1', () => { mio++; });
    _dcimSend = async () => ({ok: true});
    _dcFileDrop('f1', 'x');
    await pend;
    __out.ficheros = [mio, seccion, _dcFiles];
    renderDcim = rd;

    // F20: a cut whose second step failed retries without a second new leg.
    const cortes = [];
    let vez = 0;
    _dcimSend = async (m, u) => { cortes.push(m); return {ok: m === 'POST' || ++vez > 1}; };
    _dcCableOf = () => ({a_item: 'A', b_item: 'B', kind: 'utp'});
    hideInfoModal = () => {};
    _dcCablesOpen = () => {};
    _dcSplit = {uid: 'c1', side: 'a', pick: {uid: 'P'}, port: '3'};
    await _dcSplitSave();
    await _dcSplitSave();
    __out.corte = cortes;

    // F20: a socket clicked twice plugs one cable.
    const [pe, re] = tarde();
    const tomas = [];
    _dcimSend = (m) => { tomas.push(m); return pe; };
    _dcPowerOpen = () => {};
    _dcFeedPick = {item: 'i1', uid: '', pdu: 'p'};
    const e1 = _dcFeedPut('p', 3), e2 = _dcFeedPut('p', 3);
    re({ok: true}); await e1; await e2;
    __out.toma = tomas.length;

    // F20: a model's picture lands in that model, not in the one opened meanwhile.
    FormData = function () { this.append = () => {}; };
    const [pf, rf] = tarde();
    fetch = () => pf;
    _dcCatFormDraw = () => {};
    _dcCatOpen = () => {};
    const A = {uid: 'A'}, B = {uid: 'B'};
    _dcCatEditing = A;
    const sub = _dcCatImgUp('front', {files: [{}]});
    _dcCatEditing = B;
    rf({ok: true, json: async () => ({image: 'a.png'})});
    await sub;
    __out.foto = [A.front_image || '', B.front_image || ''];

    // F20: a rack opened in one room's 3D does not land in the next; a second click waits.
    const V3 = {key: 'room:1', escena: {cajas: []}};
    ss3dGet = () => V3;
    ss3dCard = () => {};
    _dc3dSelOpening = () => {};
    const [pr, rr] = tarde();
    let pedidosRack = 0;
    apiGet = () => { pedidosRack++; return pr; };
    _dc3dOpenRacks.clear();
    const o1 = _dc3dOpenRack('r1'), o2 = _dc3dOpenRack('r1');
    V3.key = 'room:2';
    rr({rack: {uid: 'r1'}, items: []});
    await o1; await o2;
    __out.rack3d = [_dc3dOpenRacks.has('r1'), pedidosRack];

    // F20: a search answering after the viewer was replaced flies nothing.
    let volo = 0;
    _dc3dGoTo = () => { volo++; };
    ss3dSay = () => {};
    _dcsPlan = {site: {uid: 'S'}};
    const viejo = {escena: {cajas: [{lee: {uid: 'r1'}}]}};
    let actual = viejo;
    ss3dGet = () => actual;
    const [pq, rq] = tarde();
    apiGet = () => pq;
    const bq = _dc3dSearch('nada', 'site');
    actual = {escena: {cajas: []}};
    rq({items: [{rack_uid: 'r1'}]});
    await bq;
    __out.busca = volo;

    // F20: the decoded-image cache has a ceiling.
    for (let i = 0; i < 20; i++) _ss3dImageCanvas('data:image/png;base64,' + i);
    __out.imagenes = _SS3D_IMG.size;

    // F20: a camera from the address stays where the mouse could have put it.
    _dc3dUrlTake(new URLSearchParams('cam=0,0,0,-5,1,0'));
    __out.camara = [_dc3dPendingCam.radio, _dc3dPendingCam.phi];
    _dc3dPendingCam = null;
})();
"""

_STATUS_PROBE = r"""
__out = {};
AbortController = function () { this.signal = {}; this.abort = () => {}; };
function nodo(id) {
    const s = [];
    return {id, style: {}, dataset: {}, innerHTML: '',
            classList: {add: c => { if (!s.includes(c)) s.push(c); },
                        remove: c => { const k = s.indexOf(c); if (k >= 0) s.splice(k, 1); },
                        toggle: (c, on) => on ? (s.includes(c) || s.push(c)) : (s.includes(c) && s.splice(s.indexOf(c), 1)),
                        contains: c => s.includes(c)}};
}
let dom = {};
function pinta() {          // the server's markup: a healthy module, folded
    const hdr = nodo(); hdr.classList.add('collapsed');
    const card = nodo('mod-disk'); card.querySelector = () => hdr;
    const body = nodo('body-disk'); body.style.display = 'none';
    dom = {'mod-disk': card, 'body-disk': body, 'status-body': nodo('status-body'), hdr};
}
pinta();
document.getElementById = (id) => dom[id] || null;
document.querySelector = (sel) => (sel.indexOf('mod-disk') >= 0 ? dom.hdr : null);
fetch = async () => ({ok: true, text: async () => { pinta(); return '<div></div>'; }});

__wait = (async () => {
    toggleMod('disk');
    const abierto = [dom['body-disk'].style.display, dom.hdr.classList.contains('collapsed')];
    await _stRefresh();
    __out.estado = [abierto, [dom['body-disk'].style.display, dom.hdr.classList.contains('collapsed')]];
})();
"""


def _make_wa():
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    return wa


@pytest.fixture(scope='module')
def client():
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    c = _make_wa().app.test_client()
    _login(c)
    return c


@pytest.fixture(scope='module')
def out(client):
    return node_run(panel_bundle(client), _PROBE)


@pytest.fixture(scope='module')
def status_out(client):
    html = client.get('/status').get_data(as_text=True)
    trozos = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    assert trozos, '/status served no script'
    return node_run(max(trozos, key=len), _STATUS_PROBE)


class TestOverviewAndInfra:

    def test_reset_to_factory_is_taken_when_the_server_says_ok(self, out):
        assert out['fabrica'] == [True, False]

    def test_a_table_asked_again_ends_on_the_new_filter(self, out):
        pedidas, filas = out['tabla']
        assert pedidas == ['/x?f=a', '/x?f=b']
        assert filas == ['b']

    def test_one_missed_poll_does_not_lose_the_collection(self, out):
        assert out['sondeo'] == ['J', 0]
        assert out['perdido'] == [None, 1]


class TestDcimForms:

    def test_typed_values_survive_a_repaint(self, out):
        assert out['guardado'] == ['24', '1,5', False]

    def test_the_cable_and_power_forms_are_kept_and_render_keeps_them(self, out):
        assert out['marcas'] == [True, True, True]


class TestDcim3d:

    def test_leaving_dcim_lets_the_rack_viewer_go(self, out):
        assert out['salir'] == ['dcr3d-box']

    def test_the_live_refresh_skips_a_viewer_out_of_sight(self, out):
        assert out['vivo'] == [0, 1]

    def test_a_rack_opened_in_another_room_does_not_land(self, out):
        assert out['rack3d'] == [False, 3]

    def test_a_late_search_flies_nothing(self, out):
        assert out['busca'] == 0

    def test_the_image_cache_is_bounded(self, out):
        assert 0 < out['imagenes'] <= 8

    def test_a_camera_from_the_address_is_clamped(self, out):
        radio, phi = out['camara']
        assert radio >= 0.5 and phi >= 0.08


class TestDcimSmall:

    def test_a_clone_says_how_many_rows_it_wrote(self, out):
        assert out['clon'] and '7' in out['clon'][0]

    def test_a_dropped_file_repaints_whoever_drew_the_list(self, out):
        mio, seccion, files = out['ficheros']
        assert mio == 2 and seccion == 0 and files is None

    def test_a_retried_cut_creates_one_leg(self, out):
        assert out['corte'] == ['POST', 'PUT', 'PUT']

    def test_a_socket_clicked_twice_plugs_one_cable(self, out):
        assert out['toma'] == 1

    def test_a_models_picture_lands_in_that_model(self, out):
        assert out['foto'] == ['a.png', '']


class TestStatusPage:

    def test_what_the_reader_opened_stays_open_across_a_refresh(self, status_out):
        abierto, tras = status_out['estado']
        assert abierto == ['', False]
        assert tras == ['', False]


class TestAssetVersion:

    def test_any_static_file_bumps_the_version(self, tmp_path):
        from lib.web_admin.mixins.context import _ContextMixin       # noqa: PLC0415
        (tmp_path / 'css').mkdir()
        (tmp_path / 'js').mkdir()
        css = tmp_path / 'css' / 'web_admin.css'
        bs = tmp_path / 'css' / 'bootstrap.min.css'
        js = tmp_path / 'js' / 'bootstrap.bundle.min.js'
        for f in (css, bs, js):
            f.write_text('x', encoding='utf-8')
        viejo = int(time.time()) - 86400
        os.utime(css, (viejo, viejo))
        os.utime(js, (viejo, viejo))
        nuevo = viejo + 3600
        os.utime(bs, (nuevo, nuevo))

        class _App:
            static_folder = str(tmp_path)

        assert _ContextMixin._asset_version(None, _App()) == nuevo

    def test_an_unreadable_folder_is_zero(self, tmp_path):
        from lib.web_admin.mixins.context import _ContextMixin       # noqa: PLC0415

        class _App:
            static_folder = str(tmp_path / 'missing')

        assert _ContextMixin._asset_version(None, _App()) == 0
