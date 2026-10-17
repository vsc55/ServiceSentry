#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalogue › Library: the side drawer of a brand and of a model.

A brand row went straight to that brand's models, and a model row opened a dialog with nine
tabs; both took the reader away from the list to answer what is asked of a row: how to get
support from this brand and with which account, and what this model is. The drawer answers it
beside the list (`showDrawer`, the panel's offcanvas), and goes on from there — to the brand's
models (or one of its shapes), its platforms, or the model's full record, which still exists.

All in node, over the panel's own bundle: the generic drawer helper filling a real enough DOM,
then what each drawer says and where each of its buttons goes.
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
// 1. The generic helper: title, body and the header's actions in place, shown once.
const nodos = {};
const nodo = (id) => nodos[id] || (nodos[id] = {id, innerHTML: '', textContent: '',
    classList: {_s: [], add(c) { this._s.push(c); }, contains(c) { return this._s.includes(c); }},
    querySelectorAll: () => []});
const _getReal = document.getElementById;
document.getElementById = (id) => id.startsWith('ssDrawer') ? nodo(id) : _getReal(id);
let mostrado = 0, oculto = 0;
bootstrap.Offcanvas = {getOrCreateInstance: () => ({show() { mostrado++; }}),
                       getInstance: () => ({hide() { oculto++; }})};
showDrawer('Acme', '<p>cuerpo</p>', '<button class="btn btn-secondary">x</button>');
__o.helper = {title: nodos.ssDrawerTitle.textContent, body: nodos.ssDrawerBody.innerHTML,
              actions: nodos.ssDrawerActions.innerHTML, shown: mostrado};
nodos.ssDrawer.classList.add('show');
showDrawer('Otra', '', '');
__o.helperRefill = {shown: mostrado, title: nodos.ssDrawerTitle.textContent};
hideDrawer();
__o.helperHide = oculto;

// From here the helper is watched, not run.
let cajon = null;
showDrawer = (tt, h, a) => { cajon = {tt, h, a}; };
let cerrado = 0;
hideDrawer = () => { cerrado++; };
const may = new Set(['dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
let fui = [];
_dcLibGo = (s) => { fui.push(s); };
const hoy = new Date();
const iso = (d) => new Date(hoy.getTime() + d * 86400000).toISOString().slice(0, 10);
_dcBrands = {rows: [
    {uid: 'b1', name: 'Acme', description: 'conmutadores', url: 'https://acme.example',
     support_url: 'https://help.acme.example', account: 'C-1',
     trees: {'device-types': 2, 'component-types': 1}, models: 3, platforms: 2,
     in_use: {items: 4, models: 2, racks: 1, sites: 1}},
    {uid: 'b2', name: 'Borealis', description: '', url: '', support_url: '', account: '',
     trees: {}, models: 0, platforms: 0}]};
_dcPlats = {rows: [
    {uid: 'p1', name: 'AcmeOS 1', brand_uid: 'b1', extra: {eol: iso(-30)}},
    {uid: 'p2', name: 'AcmeOS 2', brand_uid: 'b1', extra: {eol: iso(60)}},
    {uid: 'p3', name: 'Other', brand_uid: 'b2', extra: {}}], kinds: [], lifecycle: []};

// 2. A brand: how to get support, its models by shape, its platforms with their support.
await _dcLibBrandDrawer('b1');
const h = cajon.h;
__o.brand = {title: cajon.tt,
             web: h.includes('href="https://acme.example"'),
             support: h.includes('href="https://help.acme.example"'),
             copy: h.includes('_dcLibCopy(&quot;C-1&quot;)'),
             shapes: (h.match(/_dcLibBrandModels\(&quot;b1&quot;,&quot;[a-z-]+&quot;\)/g) || []).length,
             placed: h.includes(esc(tf('dcim_lib_placed_n', 4))),
             gone: /bg-danger-subtle text-danger-emphasis[^>]*>[^<]*<\/span>/.test(h) && h.includes('AcmeOS 1')
                   && h.includes(esc(tf('dcim_lib_eos_ended_on', ''))),
             soon: /bg-warning-subtle text-warning-emphasis[^>]*>/.test(h) && h.includes('AcmeOS 2'),
             notOthers: !h.includes('>Other<'),
             all: h.includes(esc(tf('dcim_lib_see_models', 3))),
             edit: cajon.a.includes('_dcLibBrandEdit(&quot;b1&quot;)')};
await _dcLibBrandDrawer('b2');
__o.brandEmpty = {account: cajon.h.includes(esc(t('dcim_lib_no_account'))),
                  noHw: cajon.h.includes(esc(t('dcim_lib_no_hw'))),
                  noAll: !cajon.h.includes('_dcLibBrandModels(&quot;b2&quot;,&quot;&quot;)')};
may.delete('dcim_catalog_manage');
await _dcLibBrandDrawer('b1');
__o.brandReaderActions = cajon.a;
may.add('dcim_catalog_manage');

// 3. From the brand: to its models of one shape, with nothing else set — and the drawer shut.
_dcCatQ = 'stale';
_dcCatKind = 'server';
cerrado = 0;
_dcLibBrandModels('b1', 'component-types');
__o.toModels = {brand: _dcCatBrand, name: _dcCatBrandName, tree: _dcCatTree, q: _dcCatQ,
                kind: _dcCatKind, view: _dcCatView, went: fui.slice(), closed: cerrado};
fui = [];
_dcPlatQ = 'x';
_dcPlatEos = 'gone';
_dcLibBrandPlats('b1');
__o.toPlats = {brand: _dcPlatBrand, q: _dcPlatQ, eos: _dcPlatEos, went: fui.slice()};
let editada = '';
_dcBrandEdit = (u) => { editada = u; };
_dcLibBrandEdit('b1');
__o.edit = editada;

// 4. A model: picture or its absence, the brand as a way to its drawer, what it is.
_dcCat = {rows: [
    {uid: 't1', manufacturer: 'Acme', model: 'SW-48', brand_uid: 'b1', tree: 'device-types',
     kind: 'switch', u_tenths: 20, ports: {interfaces: {'1000base-t': 48}}, source: 'library',
     imported_at: '2026-10-01T10:00:00Z', front_image: 'sw48.png', placed: 5, in_builds: 2,
     part_number: 'SW48-X', rear_image: 'sw48r.png', ports_total: 48, bays_total: 0,
     description: 'Normas: ISO 11801\nRango: -20 a +70 °C'},
    {uid: 't3', manufacturer: 'Acme', model: 'Front-Only', brand_uid: 'b1', tree: 'device-types',
     kind: 'switch', u_tenths: 10, ports: {}, source: 'library', imported_at: '',
     front_image: 'fo.png', rear_image: ''},
    {uid: 't2', manufacturer: 'Cumulus', model: 'Hand-1', brand_uid: '', tree: 'device-types',
     kind: '', u_tenths: 10, ports: {}, source: 'manual', imported_at: '', front_image: ''}]};
_dcLibModelDrawer('t1');
const m = cajon.h;
__o.model = {title: cajon.tt, img: m.includes('<img') && m.includes('sw48.png'),
             brandLink: m.includes('_dcLibBrandDrawer(&quot;b1&quot;)'),
             height: m.includes('2 U'), pn: m.includes('SW48-X'),
             placed: m.includes('>5 · ' + esc(tf('dcim_lib_in_builds', 2)) + '<'),
             full: cajon.a.includes('_dcLibModelFull(&quot;t1&quot;)'),
             edit: cajon.a.includes('_dcLibModelEdit(&quot;t1&quot;,false)'),
             clone: cajon.a.includes('_dcLibModelEdit(&quot;t1&quot;,true)'),
             drop: cajon.a.includes('_dcLibModelDrop(&quot;t1&quot;)')};
// Both faces, each with its name; the port editor from here, shutting the drawer first.
__o.faces = {front: m.includes('sw48.png') && m.includes(`>${esc(t('dcim_cat_front'))}<`),
             rear: m.includes('sw48r.png') && m.includes(`>${esc(t('dcim_cat_rear'))}<`),
             place: cajon.a.includes('hideDrawer();_dcPmOpen(&quot;t1&quot;)')};
_dcLibModelDrawer('t3');
// A description written in a textarea keeps its line breaks: escaped text in an element that
// honours them (`ss-prewrap`), here and in the full record's rows — not a <br> spliced in.
__o.breaks = {drawer: /<p class="[^"]*ss-prewrap[^"]*">Normas: ISO 11801\nRango/.test(m),
              full: /<td class="ss-prewrap">Normas: ISO 11801\nRango/.test(
                  _dcimDato(t('dcim_cat_desc'), 'Normas: ISO 11801\nRango: -20 a +70 °C')),
              escaped: /<td class="ss-prewrap">&lt;b&gt;/.test(_dcimDato('x', '<b>'))};
__o.faces.oneMissing = cajon.h.includes('fo.png') && cajon.h.includes(esc(t('dcim_pm_no_image')))
                       && !cajon.h.includes(esc(t('dcim_lib_q_no_image')));
__o.faces.placeOff = !cajon.a.includes('_dcPmOpen(')
                     && cajon.a.includes(`disabled title="${escAttr(t('dcim_pm_no_ports'))}"`);
_dcLibModelDrawer('t2');
__o.model2 = {noImg: cajon.h.includes('ss-drawer-noimg'),
              noSheet: cajon.h.includes(esc(t('dcim_lib_no_sheet'))),
              noLink: !cajon.h.includes('_dcLibBrandDrawer('),
              hand: cajon.h.includes(esc(t('dcim_lib_src_manual'))),
              noPlaced: !cajon.h.includes(esc(t('dcim_lib_col_placed')))};
may.delete('dcim_catalog_manage');
_dcLibModelDrawer('t1');
__o.modelReader = {full: cajon.a.includes('_dcLibModelFull('),
                   edit: cajon.a.includes('_dcLibModelEdit('),
                   drop: cajon.a.includes('_dcLibModelDrop('),
                   place: cajon.a.includes('bi-geo')};
may.add('dcim_catalog_manage');
cajon = null;
_dcLibModelDrawer('nope');
__o.unknown = cajon;

// 5. «Full record» shuts the drawer and opens the dialog of always.
let ficha = '';
_dcCatShow = (u) => { ficha = u; };
cerrado = 0;
_dcLibModelFull('t1');
__o.full = {sheet: ficha, closed: cerrado};
let editando = null;
_dcCatRowEdit = (u, c) => { editando = [u, c]; };
_dcLibModelEdit('t1', true);
__o.clone = editando;
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


@pytest.fixture(scope='module')
def page():
    """The panel's HTML, for the drawer's markup."""
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tempfile.mkdtemp(prefix='ss-cfg-')
    var = tempfile.mkdtemp(prefix='ss-var-')
    io.open(os.path.join(cfg, 'config.json'), 'w', encoding='utf-8').write('{}')
    wa = WebAdmin(cfg, 'admin', 'secret', var, pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    return c.get('/admin').get_data(as_text=True)


class TestTheMarkup:

    def test_one_offcanvas_with_its_three_slots(self, page):
        i = page.index('id="ssDrawer"')
        trozo = page[page.rindex('<div', 0, i):page.index('id="ssDrawerBody"') + 40]
        assert 'offcanvas offcanvas-end ss-drawer' in trozo
        for slot in ('ssDrawerTitle', 'ssDrawerActions', 'ssDrawerBody'):
            assert f'id="{slot}"' in trozo, slot
        assert 'data-bs-dismiss="offcanvas"' in trozo


@_needs_node
class TestTheHelper:

    def test_fills_the_three_slots_and_shows_once(self, out):
        assert out['helper'] == {'title': 'Acme', 'body': '<p>cuerpo</p>',
                                 'actions': '<button class="btn btn-secondary">x</button>',
                                 'shown': 1}

    def test_an_open_drawer_is_refilled_not_reopened(self, out):
        assert out['helperRefill'] == {'shown': 1, 'title': 'Otra'}
        assert out['helperHide'] == 1


@_needs_node
class TestTheBrandsDrawer:

    def test_how_to_get_support_and_what_it_makes(self, out):
        assert out['brand'] == {'title': 'Acme', 'web': True, 'support': True, 'copy': True,
                                'shapes': 2, 'placed': True, 'gone': True, 'soon': True,
                                'notOthers': True, 'all': True, 'edit': True}

    def test_what_is_missing_is_said(self, out):
        assert out['brandEmpty'] == {'account': True, 'noHw': True, 'noAll': True}

    def test_a_reader_cannot_edit(self, out):
        assert out['brandReaderActions'] == ''

    def test_to_its_models_of_one_shape_with_nothing_else_set(self, out):
        assert out['toModels'] == {'brand': 'b1', 'name': 'Acme', 'tree': 'component-types',
                                   'q': '', 'kind': '', 'view': 'list', 'went': ['models'],
                                   'closed': 1}

    def test_to_its_platforms(self, out):
        assert out['toPlats'] == {'brand': 'b1', 'q': '', 'eos': '', 'went': ['platforms']}
        assert out['edit'] == 'b1'


@_needs_node
class TestTheModelsDrawer:

    def test_what_the_model_is(self, out):
        assert out['model'] == {'title': 'Acme SW-48', 'img': True, 'brandLink': True,
                                'height': True, 'pn': True, 'placed': True, 'full': True,
                                'edit': True, 'clone': True, 'drop': True}

    def test_a_description_keeps_its_line_breaks(self, out):
        """Written in a textarea, drawn as one run-on paragraph: the breaks were lost."""
        assert out['breaks'] == {'drawer': True, 'full': True, 'escaped': True}

    def test_both_faces_and_the_port_editor(self, out):
        """Only the front was shown, and the drawer had no way to place the ports."""
        assert out['faces'] == {'front': True, 'rear': True, 'place': True,
                                'oneMissing': True, 'placeOff': True}

    def test_no_picture_no_record_and_no_placed_count_it_was_not_asked_for(self, out):
        assert out['model2'] == {'noImg': True, 'noSheet': True, 'noLink': True,
                                 'hand': True, 'noPlaced': True}

    def test_a_reader_has_the_full_record_and_nothing_to_edit(self, out):
        assert out['modelReader'] == {'full': True, 'edit': False, 'drop': False,
                                      'place': False}
        assert out['unknown'] is None

    def test_the_full_record_is_the_dialog_of_always(self, out):
        assert out['full'] == {'sheet': 't1', 'closed': 1}
        assert out['clone'] == ['t1', True]
