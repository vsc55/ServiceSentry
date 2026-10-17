#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalogue › Library: importing is a dialog, not a view — and it tells you when it ends.

It was a tab of the library, the size of a page, for something done twice a year. Now:

* «Import…» opens a dialog (a manager's) with the three doors and «Bring the basics»; the two
  heavy confirmations — the basics replace the panel's own, the whole library is 850 MB — are
  asked in a band INSIDE the dialog rather than in a second dialog stacked on the first;
* while an import runs the library's header carries a pill with how far it is, which reopens
  the dialog; the dialog itself shows the progress and says it can be closed;
* the end is announced with a toast wherever the reader is — the watcher no longer dies when
  somebody leaves the library for the inventory — and what the import made stale is dropped.
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


_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
const may = new Set(['dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
_sbHighlightSub = () => {};
let modal = null;
showHtmlModal = (tt, h, v, a, size) => { modal = {tt, h, size}; };
let dialogos = 0;
showConfirmModal = () => { dialogos++; };
let cerrados = 0;
hideInfoModal = () => { cerrados++; };
let avisos = [];
showToast = (m, k) => { avisos.push([m, k]); };
let envios = [];
_dcimSend = async (m, u, b) => { envios.push([m, u, b]); return {ok: true, data: {count: 3, job: 'j9'}}; };
let pintados = 0;
renderDcim = () => { pintados++; };
let frescos = 0;
_dcCatFresh = () => { frescos++; };
let vigilado = 0;
const _watchReal = _dcCatWatch;
// The dialog on screen, with its box: a node that remembers what is written in it.
let caja = {_h: '', escrito: 0, get innerHTML() { return this._h; },
            set innerHTML(v) { this._h = v; this.escrito++; }};
let abierto = true;
const _getReal = document.getElementById;
document.getElementById = (id) => id === 'dclib-import' ? caja
    : id === 'infoModal' ? {classList: {contains: (c) => c === 'show' && abierto}}
    : _getReal(id);

// 1. The dialog: a manager's, wide, with the doors and the basics.
_dcCat = {rows: [], job: null, counts: {}};
_dcLibImportOpen();
__o.open = {title: modal.tt, box: modal.h.includes('id="dclib-import"'), size: modal.size,
            doors: modal.h.includes("_dcCatGoFrom('upload')") && modal.h.includes("_dcCatGoFrom('path')"),
            basics: modal.h.includes('_dcCatBasics()')};
may.delete('dcim_catalog_manage');
modal = null;
_dcLibImportOpen();
__o.openReader = modal;
__o.headReader = _dcLibHeadHtml('summary').includes('_dcLibImportOpen()');
may.add('dcim_catalog_manage');
__o.headManager = _dcLibHeadHtml('summary').includes('_dcLibImportOpen()');

// 2. The basics ask in a band inside the dialog, and only then go.
_dcCatBasics();
__o.basicsAsk = {ask: _dcCatAskImport, dialogs: dialogos,
                 band: _dcCatImportHtml(null).includes('ss-selband-warn')
                       && _dcCatImportHtml(null).includes('_dcCatBasicsGo()')};
await _dcCatBasicsGo();
__o.basicsGo = {sent: envios.slice(), ask: _dcCatAskImport, closed: cerrados, fresh: frescos};
envios = [];
cerrados = 0;

// 3. The whole library: the same band, then the job and its watcher.
_dcCatVendors = {url: 'https://github.com/example/lib', vendors: []};
_dcCatImportAll();
__o.allAsk = {ask: _dcCatAskImport, dialogs: dialogos,
              band: _dcCatImportHtml(null).includes('_dcCatImportAllGo()')};
_dcCatWatch = () => { vigilado++; };
await _dcCatImportAllGo();
__o.allGo = {sent: envios.slice(), job: _dcCatJob, watched: vigilado, ask: _dcCatAskImport};
_dcCatWatch = _watchReal;

// 4. While it runs: the progress in the dialog, the note that it can be closed, the pill.
const J = {id: 'j9', done: false, total: 10, fetched: 5, count: 5, phase: 'models'};
const p = _dcCatImportHtml(J);
__o.progress = {bar: p.includes('width:50%'), note: p.includes(esc(t('dcim_lib_import_bg'))),
                noDoors: !p.includes("_dcCatGoFrom(")};
_dcCat = {rows: [], job: J, counts: {}};
const pill = _dcLibPillHtml();
__o.pill = {pct: pill.includes('50%'), reopens: pill.includes('_dcLibImportOpen()'),
            inHead: _dcLibHeadHtml('list').includes(pill)};
_dcCat.job = Object.assign({}, J, {done: true});
__o.pillDone = _dcLibPillHtml();
_dcCat.job = null;
__o.pillNone = _dcLibPillHtml();

// 5. The dialog is rewritten only when what it says changed (a rewrite empties a chosen zip).
_dcCat = {rows: [], job: null, counts: {}};
_dcLibImportLast = '';
caja.escrito = 0;
_dcLibImportRedraw();
_dcLibImportRedraw();
__o.rewrites = caja.escrito;
abierto = false;
_dcCat.job = J;
caja.escrito = 0;
_dcLibImportRedraw();
__o.closedNotRewritten = caja.escrito;
abierto = true;

// 6. The watcher, with the library NOT on screen: the box moves, the end is told, the rest
//    is forgotten — and nothing of the library is drawn over another section.
_dcimApartPane = () => '';
_dcCat = {rows: [], job: null, counts: {}};
_dcCatJob = 'j9';
_dcCatWatching = false;
let respuesta = {id: 'j9', done: false, total: 4, fetched: 1, count: 1, phase: 'models'};
apiGet = async () => respuesta;
setTimeout = () => 0;
pintados = 0;
caja.escrito = 0;
_dcLibImportLast = '';
await _dcCatWatch();
__o.tickOff = {painted: pintados, boxMoved: caja.escrito > 0,
               bar: caja.innerHTML.includes('width:25%')};
respuesta = {id: 'j9', done: true, count: 7};
avisos = [];
cerrados = 0;
frescos = 0;
_dcLibSum = {models: {}};
await _dcCatWatch(true);
__o.doneOff = {toast: avisos.slice(), closed: cerrados, fresh: frescos, cat: _dcCat,
               sum: _dcLibSum, job: _dcCatJob};
// …and with it on screen: drawn, and opened afresh.
_dcimApartPane = () => 'models';
_dcCat = {rows: [], job: null, counts: {}};
_dcCatJob = 'j9';
respuesta = {id: 'j9', done: false, total: 0, count: 2};
pintados = 0;
await _dcCatWatch(true);
__o.tickOn = pintados;
respuesta = {id: 'j9', done: true, error: 'boom', count: 0};
avisos = [];
frescos = 0;
await _dcCatWatch(true);
__o.doneOn = {toast: avisos.slice(), fresh: frescos};

// 7. Leaving the library for another view of the inventory does not kill the watcher.
_dcCatJob = 'j10';
_dcWireOpen = () => {};
window.history = {replaceState() {}, pushState() {}};
_dcimGo('wiring');
__o.survives = _dcCatJob;
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


@_needs_node
class TestTheDialog:

    def test_a_manager_opens_it_wide_with_the_doors_and_the_basics(self, out):
        o = out['open']
        assert o['box'] and o['size'] == 'wide' and o['doors'] and o['basics']
        assert o['title']

    def test_a_reader_has_neither_the_dialog_nor_its_button(self, out):
        assert out['openReader'] is None
        assert out['headReader'] is False and out['headManager'] is True


@_needs_node
class TestTheHeavyConfirmationsAreAskedInTheDialog:

    def test_the_basics(self, out):
        assert out['basicsAsk'] == {'ask': 'basics', 'dialogs': 0, 'band': True}
        g = out['basicsGo']
        assert g['sent'] == [['POST', '/api/v1/dcim/catalog/basics', {'images': True}]]
        assert g['ask'] == '' and g['closed'] == 1 and g['fresh'] == 1

    def test_the_whole_library(self, out):
        assert out['allAsk'] == {'ask': 'all', 'dialogs': 0, 'band': True}
        g = out['allGo']
        assert g['sent'] == [['POST', '/api/v1/dcim/catalog/import',
                              {'github': 'https://github.com/example/lib', 'all': True,
                               'source': 'library'}]]
        assert g['job'] == 'j9' and g['watched'] == 1 and g['ask'] == ''


@_needs_node
class TestWhileItRuns:

    def test_the_dialog_shows_the_progress_and_says_it_can_be_closed(self, out):
        assert out['progress'] == {'bar': True, 'note': True, 'noDoors': True}

    def test_the_header_carries_a_pill_that_reopens_it(self, out):
        assert out['pill'] == {'pct': True, 'reopens': True, 'inHead': True}
        assert out['pillDone'] == '' and out['pillNone'] == ''

    def test_the_dialog_is_rewritten_only_when_it_changes_and_only_when_open(self, out):
        assert out['rewrites'] == 1
        assert out['closedNotRewritten'] == 0


@_needs_node
class TestTheEnd:

    def test_off_the_library_the_box_moves_and_nothing_is_drawn(self, out):
        assert out['tickOff'] == {'painted': 0, 'boxMoved': True, 'bar': True}

    def test_off_the_library_the_end_is_told_and_the_stale_forgotten(self, out):
        d = out['doneOff']
        assert d['toast'] and d['toast'][0][1] == 'success' and '7' in d['toast'][0][0]
        assert d['closed'] == 1 and d['fresh'] == 0
        assert d['cat'] is None and d['sum'] is None and d['job'] == ''

    def test_on_the_library_it_is_drawn_and_opened_afresh(self, out):
        assert out['tickOn'] == 1
        assert out['doneOn']['fresh'] == 1

    def test_an_import_that_failed_is_told_too(self, out):
        """A finished job carries `error` when it failed — and so does the 404 of a job that
        does not exist. The watcher read both as «nothing to watch», so a failed import ended
        in silence."""
        assert out['doneOn']['toast'] == [['boom', 'danger']]

    def test_leaving_for_the_inventory_does_not_kill_the_watcher(self, out):
        assert out['survives'] == 'j10'
