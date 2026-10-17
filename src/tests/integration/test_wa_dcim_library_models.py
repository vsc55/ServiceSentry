#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalogue › Library › Models: the filters the server answers, and the toolbar that sets them.

The server side (`GET /api/v1/dcim/catalog`):

* the data-quality filters each figure of the Summary lands on — no front image
  (`img=none`), devices without ports (`ports=none`), a brand written with no brand record
  (`brand_uid=none`), written by hand (`source=manual`), one import (`import=<source>@<at>`) and
  never placed nor in a template (`unused=1`);
* «placed» is the inventory answering: only with `dcim_view`, and over what the caller may see
  (the company boundary) — the column (`placed=1`) and the `unused` filter alike;
* the brand grid obeys every filter but the brand's own, so the search box means the same in
  both views; the shape buttons count what the OTHER filters leave.

* sorted and paged there too (`sort`/`dir`, whitelisted, blanks last both ways; `limit` up to
  the server's page) — the list is paged on the server, so sorting a page would sort a sample.

The panel side, in node: the list is the shared `createListTable` card (`serverPaging`) — no
title row of the library above it, the shapes and filters inside the card, pagination bands
with a page-size selector, sortable headers that ask the server, an actions column on every
row (edit, clone, place ports, delete) and a row that opens its drawer; the chips that say what is set and take
it off, the band over what is ticked (asking in the band, never in a dialog), the column
chooser, the header search and the grid that keeps the filters.
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


def _as(admin, username, perms):
    """A session holding exactly *perms*, through a role of its own."""
    from tests.integration.test_wa_dcim import _as as _dcim_as      # noqa: PLC0415
    return _dcim_as(admin, username, perms)


@pytest.fixture()
def lib(client, admin):
    """An import of three, two hand-written models (one from before sources existed), two
    companies with one item placed each and a template naming a hand-written one."""
    _login(client)
    c = client
    cat = admin._dcim_catalog
    cat.replace('library', [
        {'manufacturer': 'Acme', 'model': 'SW-48', '_tree': 'device-types',
         'ports': {'interfaces': {'1000base-t': 48}}},
        {'manufacturer': 'Acme', 'model': 'Blank-1U', 'description': 'blanking plate 42U',
         '_tree': 'device-types'},
        {'manufacturer': 'Borealis', 'model': 'R42', '_tree': 'rack-types'},
    ])
    uid = {r['model']: r['uid'] for r in cat.list()}
    uid['Hand-1'] = _uid(c.post('/api/v1/dcim/catalog',
                                json={'manufacturer': 'Cumulus', 'model': 'Hand-1'}))
    # And one from before sources existed: no source at all, which is «written by hand» too.
    uid['Old-1'] = _uid(c.post('/api/v1/dcim/catalog',
                               json={'manufacturer': 'Cumulus', 'model': 'Old-1'}))
    cat._db.execute("UPDATE dc_type SET source = '' WHERE uid = ?", (uid['Old-1'],))
    cat.set_image(uid['SW-48'], 'front', 'sw48.png')
    # The brand record of the hand-written one is gone: the brand is only written.
    cat._db.execute("UPDATE dc_type SET brand_uid = '' WHERE uid = ?", (uid['Hand-1'],))
    cat._db.commit()
    org = lambda n: _uid(c.post('/api/v1/orgs', json={'name': n, 'short': n}))  # noqa: E731
    a, b = org('A'), org('B')
    for nombre, empresa, tipo in (('SA', a, uid['SW-48']), ('SB', b, uid['Blank-1U'])):
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': nombre}))
        c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': site, 'org_uid': empresa})
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}))
        rack = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                        'u_height': 42}))
        _uid(c.post('/api/v1/dcim/items', json={'rack_uid': rack, 'u_start': 1, 'u_height': 1,
                                                 'label': nombre, 'type_uid': tipo}))
    _uid(c.post('/api/v1/dcim/builds', json={'name': 'Std', 'type_uid': uid['Hand-1']}))
    fuente, cuando, _n = cat.imports()[0]
    return {'uid': uid, 'a': a, 'b': b, 'admin': admin, 'import': f'{fuente}@{cuando}'}


def _models(c, q=''):
    d = c.get('/api/v1/dcim/catalog' + (('?' + q) if q else '')).get_json()
    return d, sorted(r['model'] for r in d['types'])


class TestTheQualityFilters:

    def test_no_front_image(self, client, lib):
        assert _models(client, 'img=none')[1] == ['Blank-1U', 'Hand-1', 'Old-1', 'R42']

    def test_devices_without_ports_and_only_devices(self, client, lib):
        """A rack or a blank has no ports by nature; a DEVICE with none is the odd one."""
        assert _models(client, 'ports=none')[1] == ['Blank-1U', 'Hand-1', 'Old-1']

    def test_a_brand_written_with_no_record(self, client, lib):
        assert _models(client, 'brand_uid=none')[1] == ['Hand-1']

    def test_written_by_hand_and_a_source_by_its_name(self, client, lib):
        assert _models(client, 'source=manual')[1] == ['Hand-1', 'Old-1']
        assert _models(client, 'source=library')[1] == ['Blank-1U', 'R42', 'SW-48']

    def test_one_import(self, client, lib):
        assert _models(client, 'import=' + lib['import'])[1] == ['Blank-1U', 'R42', 'SW-48']
        assert _models(client, 'import=library@1999-01-01T00:00:00Z')[1] == []


class TestWhatIsPlacedIsTheInventorysAnswer:

    def test_never_placed_nor_in_a_template(self, client, lib):
        d, filas = _models(client, 'unused=1')
        assert d['usage'] is True and filas == ['Old-1', 'R42']

    def test_over_what_the_caller_may_see(self, lib):
        """Company A's reader: B's placed blank is not theirs to count."""
        ua = _as(lib['admin'], 'ua', ['dcim_view', 'dcim_catalog_view', f'org.{lib["a"]}.view'])
        assert _models(ua, 'unused=1')[1] == ['Blank-1U', 'Old-1', 'R42']

    def test_without_the_inventorys_permission_the_filter_is_not_applied(self, lib):
        solo = _as(lib['admin'], 'solo', ['dcim_catalog_view'])
        d, filas = _models(solo, 'unused=1')
        assert d['usage'] is False and len(filas) == 5

    def test_the_placed_column(self, client, lib):
        d = client.get('/api/v1/dcim/catalog?placed=1').get_json()
        por = {r['model']: (r['placed'], r['in_builds']) for r in d['types']}
        assert por == {'SW-48': (1, 0), 'Blank-1U': (1, 0), 'R42': (0, 0), 'Hand-1': (0, 1),
                       'Old-1': (0, 0)}

    def test_the_placed_column_counts_only_what_is_visible(self, lib):
        ua = _as(lib['admin'], 'ub', ['dcim_view', 'dcim_catalog_view', f'org.{lib["a"]}.view'])
        d = ua.get('/api/v1/dcim/catalog?placed=1').get_json()
        assert {r['model']: r['placed'] for r in d['types']}['Blank-1U'] == 0

    def test_and_is_not_there_without_the_permission(self, lib):
        solo = _as(lib['admin'], 'solo2', ['dcim_catalog_view'])
        d = solo.get('/api/v1/dcim/catalog?placed=1').get_json()
        assert all('placed' not in r for r in d['types'])


class TestTheGridAndTheShapesObeyTheOtherFilters:

    def test_the_search_means_models_in_the_grid_too(self, client, lib):
        """Before, the grid's box filtered brand NAMES; now each card counts its matching
        models — `42U` is only in a description, and only Acme has it."""
        d = client.get('/api/v1/dcim/catalog?q=42u').get_json()
        assert d['makers'] == [['Acme', 1]]

    def test_the_brand_does_not_filter_the_grid_of_brands(self, client, lib):
        d = client.get('/api/v1/dcim/catalog?q=42u&maker=Borealis').get_json()
        assert d['types'] == [] and d['makers'] == [['Acme', 1]]

    def test_each_shape_counts_what_the_other_filters_leave(self, client, lib):
        d = client.get('/api/v1/dcim/catalog?maker=Acme&tree=rack-types').get_json()
        assert d['total'] == 0
        assert {x['name']: x['count'] for x in d['tree_counts']} == {'device-types': 2}
        assert d['counts']['models'] == 5, 'the menu says the whole library'


def _uids(c, q):
    r = c.get('/api/v1/dcim/catalog?' + q)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    return d, [x['uid'] for x in d['types']]


@pytest.fixture()
def sorted_lib(client, admin):
    from tests.helpers import CATALOG_SORT_INSERT, CATALOG_SORT_ROWS  # noqa: PLC0415
    _login(client)
    cat = admin._dcim_catalog
    for fila in CATALOG_SORT_ROWS:
        cat._db.execute(CATALOG_SORT_INSERT.format(table='dc_type'), fila)
    cat._db.commit()
    return client


class TestTheServerSortsAndPages:
    """`GET /api/v1/dcim/catalog?sort=&dir=&limit=`: the list is paged on the server, so it is
    sorted there too — sorting a page in the browser would be sorting a sample."""

    def test_each_key_both_ways_with_the_blanks_last(self, sorted_lib):
        from tests.helpers import CATALOG_SORT_EXPECT                   # noqa: PLC0415
        for clave, (sube, baja) in CATALOG_SORT_EXPECT.items():
            d, filas = _uids(sorted_lib, f'sort={clave}&dir=asc')
            assert filas == sube, clave
            assert (d['sort'], d['dir']) == (clave, 'asc')
            assert _uids(sorted_lib, f'sort={clave}&dir=desc')[1] == baja, clave

    def test_an_unknown_key_is_the_default_order_and_not_an_error(self, sorted_lib):
        """Whitelisted: the key only ever picks one of the store's literals. A link saved
        before a column was renamed still opens the list, in the order of always."""
        for malo in ('bogus', 'maker;DROP TABLE dc_type', 'LOWER(model)', 'placed', 'ports'):
            d, filas = _uids(sorted_lib, f'sort={malo}&dir=desc')
            assert filas == ['sD', 'sB', 'sC', 'sA'], malo
            assert (d['sort'], d['dir']) == ('', 'asc'), malo
        assert _uids(sorted_lib, 'sort=model&dir=sideways')[1] == ['sB', 'sA', 'sC', 'sD']

    def test_the_page_size_is_honoured_and_capped(self, sorted_lib):
        d, filas = _uids(sorted_lib, 'sort=model&limit=2')
        assert filas == ['sB', 'sA'] and d['limit'] == 2 and d['total'] == 4
        assert _uids(sorted_lib, 'sort=model&limit=2&offset=2')[1] == ['sC', 'sD']
        for raro, tope in (('9999', 200), ('0', 200), ('-3', 200), ('abc', 200), ('', 200)):
            assert _uids(sorted_lib, f'limit={raro}')[0]['limit'] == tope, raro

    def test_without_the_new_parameters_nothing_changed(self, sorted_lib):
        """Every other caller (the item form, the templates, the parts) asks with none."""
        d, filas = _uids(sorted_lib, '')
        assert d['limit'] == 200 and d['sort'] == '' and filas == ['sD', 'sB', 'sC', 'sA']


# ── The panel, in node ─────────────────────────────────────────────────────────────────────

_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
// A container that remembers its HTML: the shared table draws the card there.
const cont = {innerHTML: '', classList: {_s: [], add(x) { this._s.push(x); },
                                         contains(x) { return this._s.includes(x); }},
              querySelector: () => null};
const _getReal = document.getElementById;
document.getElementById = (id) => (id === 'dccat-container' ? cont : _getReal(id));
const may = new Set(['dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
_sbHighlightSub = () => {};
let abiertos = 0;
_dcCatOpen = async () => { abiertos++; };
renderDcim = () => {};
let envios = [];
_dcimSend = async (m, u, b) => { envios.push([m, u, b]); return {ok: true, data: {count: 2}}; };
let dialogos = 0, pregunta = '', siAcepta = null;
showConfirmModal = (q, fn) => { dialogos++; pregunta = q; siAcepta = fn; };
showToast = () => {};
let fui = [];
_dcLibGo = (s) => { fui.push(s); };
let guardados = 0;
_persistTableConfig = () => { guardados++; };
_dcBrands = {rows: [{uid: 'b1', name: 'Acme', models: 2}, {uid: 'b2', name: 'Borealis', models: 0}]};
const D = {rows: [
    {uid: 't1', manufacturer: 'Acme', model: 'SW-48', brand_uid: 'b1', tree: 'device-types',
     kind: 'switch', u_tenths: 10, ports: {interfaces: {'1000base-t': 48}}, source: 'library',
     imported_at: '2026-10-01T10:00:00Z', placed: 3, front_image: 'sw48.png',
     ports_total: 48, ports_placed: 0, bays_total: 0, bays_placed: 0},
    {uid: 't2', manufacturer: 'Cumulus', model: 'Hand-1', brand_uid: '', tree: 'device-types',
     kind: '', u_tenths: 10, ports: {}, source: 'manual', imported_at: ''}],
    total: 60, offset: 0, limit: 25, kinds: [{name: 'switch', count: 1}],
    sources: [{name: 'library', count: 1}, {name: 'manual', count: 1}],
    trees: ['device-types', 'module-types', 'rack-types', 'component-types'],
    tree_counts: [{name: 'device-types', count: 2}], total_all: 2, usage: true,
    makers: [['Acme', 1], ['Cumulus', 1]], counts: {models: 212}};
// What the server is asked, every time the table needs another page: the stub answers with
// the same rows and remembers the question, as `_dcCatLoad` does.
let pedidos = [];
_dcCatLoad = async () => {
    const args = _dcCatQueryArgs();
    pedidos.push(args);
    _dcCat = Object.assign({}, D, {args});
};
const reset = () => { _dcCat = Object.assign({}, D, {args: _dcCatQueryArgs()}); pedidos = []; };
// What login does: a table the user never customised starts with its default columns.
_applyUserTableConfig({});
_dcCatTab = 'list';
reset();
const html = () => cont.innerHTML;
const at = (s) => html().indexOf(s);

// 1. Every filter set is a chip, and «Remove all» once there are two.
_dcCatFiltersReset();
_dcCatImp = 'library@2026-10-01T10:00:00Z';
_dcCatImg = 'none';
_dcCatNoPorts = 'none';
_dcCatUnused = '1';
_dcCatBrand = 'b1';
_dcCatKind = 'switch';
_dcCatSrc = 'manual';
_dcCatQ = 'sw';
_dcCatTree = 'rack-types';
const h1 = _dcCatToolsHtml({d: D}, 'table');
__o.chips = {n: (h1.match(/_dcCatUnfilter\(&quot;/g) || []).length,
             all: h1.includes("_dcCatUnfilter('all')"),
             brand: h1.includes(esc(tf('dcim_lib_chip_brand', 'Acme'))),
             imp: h1.includes(esc(tf('dcim_lib_chip_import', 'library', '2026-10-01'))),
             q: h1.includes(esc(tf('dcim_lib_chip_q', 'sw')))};
// 2. What travels to the server.
__o.args = _dcCatQueryArgs();
// 3. Taking one off, then all.
abiertos = 0;
_dcCatUnfilter('brand');
__o.unBrand = {brand: _dcCatBrand, kind: _dcCatKind, opened: abiertos};
_dcCatUnfilter('all');
__o.unAll = [_dcCatImp, _dcCatImg, _dcCatNoPorts, _dcCatUnused, _dcCatKind, _dcCatSrc, _dcCatQ,
             _dcCatTree].join('|');
__o.noChips = !_dcCatToolsHtml({d: D}, 'table').includes('_dcCatUnfilter(');
_dcCatBrand = 'none';
__o.chipNone = _dcCatToolsHtml({d: D}, 'table').includes(esc(t('dcim_lib_brand_none')));
_dcCatBrand = '';

// 4. The brand select: the brands with models, and «no brand record».
const sel = _dcCatBrandSelect();
__o.brandSel = {acme: sel.includes('value="b1"'), borealis: sel.includes('value="b2"'),
                none: sel.includes('value="none"')};

// 5. The band over what is ticked — manage only — and its question, asked IN the band.
_dcCatSel = new Set(['t1', 't2']);
_dcCatAsk = false;
const b1 = _dcCatBandHtml();
__o.band = {marked: b1.includes(esc(tf('dcim_lib_marked', 2))),
            export: b1.includes('_dcPortExport(Array.from(_dcCatSel)'),
            untick: b1.includes('_dcCatSelAll(false, true)'),
            ask: b1.includes('_dcCatAsk=true')};
_dcCatAsk = true;
const b2 = _dcCatBandHtml();
__o.bandAsk = {danger: b2.includes('ss-selband-danger'), go: b2.includes('_dcCatDropSelGo()'),
               question: b2.includes(esc(tf('dcim_cat_drop_sel_ask', 2)))};
await _dcCatDropSelGo();
__o.dropped = {sent: envios.slice(), dialogs: dialogos};
envios = [];
may.delete('dcim_catalog_manage');
_dcCatSel = new Set(['t1']);
__o.bandReader = _dcCatBandHtml();
may.add('dcim_catalog_manage');
_dcCatSel = new Set(['t1', 't2']);
_dcCatSelAll(false, true);
__o.untickAll = _dcCatSel.size;

// 6. The card: the library draws no title row for Models, the shared table draws the card.
reset();
__o.hole = _dcCatHtml();
await renderDcCat();
const h = html();
__o.card = {
    noTitleRow: !__o.hole.includes('dclib-q') && !__o.hole.includes('ss-toolrow'),
    header: h.includes('ss-card-header') && h.includes('bi-list-ul'),
    count: h.includes('rounded-pill ms-1 ss-tabular">212<'),
    // Header, then the tools inside the card, then the top band, the table, the bottom band.
    order: [at('ss-card-header'), at('ss-card-tools'), at('ss-card-band-top'),
            at('id="dccat-table"'), at('ss-card-band-bottom')].every((x, i, a) => x >= 0
            && (i === 0 || x > a[i - 1])),
    // Right side of the header: «New model», «Import…», the chooser, «Refresh», the menu.
    buttons: [at('_dcCatEdit(null)'), at('_dcLibImportOpen()'), at('ss-col-chooser'),
              at('onclick="_dcCatOpen()"'), at('bi-three-dots')].every((x, i, a) => x >= 0
              && (i === 0 || x > a[i - 1])) && at('bi-three-dots') < at('ss-card-tools'),
    // The rarely-used two live in the menu, not the filter row.
    more: h.includes('_dcPortImport(_dcCatOpen)') && h.includes('_dcCatEmptySrc()')
          && h.indexOf('_dcCatEmptySrc()') < at('ss-card-tools'),
    chooserCols: (h.match(/_colChooserToggle\(event,'_dccatToggleCol','([a-z]+)'\)/g) || [])
        .map(x => x.split("'")[3]),
    // Locked rows of the chooser: only «model»; the thumbnail is not in it at all.
    chooserLocked: (h.match(/bi-lock-fill/g) || []).length,
    showing: (h.match(new RegExp(esc(tf('audit_showing', 1, 25, 60)).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length,
    sizes: [...h.matchAll(/<option value="(\d+)"( selected)?>/g)].map(m => m[1] + (m[2] ? '*' : '')).slice(0, 5),
    noAll: !h.includes('<option value="0"'),
    shapesThenFilters: at('_dcCatSetTree(') < at('id="dccat-q"')
                       && at('_dcCatGoView(\'makers\')') < at('id="dccat-q"'),
    search: h.includes(`placeholder="${escAttr(t('dcim_lib_models_search'))}"`),
    thumb: h.includes('sw48.png'),
    kindBadge: h.includes(esc(_dcCatKindName('switch'))),
};
__o.reg = (() => { const r = _LIST_TABLE_REGISTRY.find(d => d.k === 'dccat');
                   return r ? {def: [...r.def()].sort(), label: r.clearLabelKey,
                               extra: r.extra && r.extra()} : null; })();

// 7. Each row has its actions column — edit, clone, delete, the buttons the old table had —
// and a click elsewhere on the row opens the drawer; the box's click does not.
__o.rows = {actions: h.includes('ss-th-actions')
                     && h.includes('_dcCatRowEdit(&quot;t1&quot;, false)')
                     && h.includes('_dcCatRowEdit(&quot;t1&quot;, true)')
                     && /_dcCatDrop\(&quot;t1&quot;, &quot;Acme SW-48&quot;\)/.test(h)
                     && /btn btn-danger[^>]*title="[^"]*"\s*onclick="_dcCatDrop\(/.test(h),
            // «Place ports» on every row, so the column stays aligned: live on the model with
            // ports to place, disabled (saying why) on the one without.
            place: h.includes('_dcPmOpen(&quot;t1&quot;)') && !h.includes('_dcPmOpen(&quot;t2&quot;)')
                   && h.includes(`title="${escAttr(t('dcim_pm_open'))}"`)
                   && h.includes(` disabled title="${escAttr(t('dcim_pm_no_ports'))}"`),
            sameWidth: (h.match(/<td class="ss-td-actions"[^>]*>[\s\S]*?<\/td>/g) || [])
                .map(c => (c.match(/<button /g) || []).length).every(n => n === 4),
            click: h.includes('_dcCatRowClick(event, &quot;t1&quot;)'),
            checks: (h.match(/_dccatToggleOne\(/g) || []).length,
            noSheet: h.includes(esc(t('dcim_lib_no_sheet')))};
let cajon = null;
showDrawer = (tt, hh, a) => { cajon = {tt, h: hh, a}; };
let cerrado = 0;
hideDrawer = () => { cerrado++; };
const fuera = {closest: () => null};
const caja = {closest: (s) => (s.includes('input') ? caja : null)};
const celda = {closest: (s) => (s === 'td' ? {querySelector: () => caja} : null)};
_dcCatRowClick({target: caja}, 't1');
__o.boxClick = cajon;
_dcCatRowClick({target: celda}, 't1');
__o.cellClick = cajon;
_dcCatRowClick({target: fuera}, 't1');
__o.rowClick = cajon && cajon.tt;
// 8. …and the drawer is where ONE model is removed, asking first in the panel's modal.
__o.drawerDrop = cajon && cajon.a.includes('_dcLibModelDrop(&quot;t1&quot;)');
dialogos = 0;
_dcLibModelDrop('t1');
await siAcepta();
__o.drop = {dialogs: dialogos, closed: cerrado,
            asked: pregunta === tf('dcim_cat_drop_ask', 'Acme SW-48'), sent: envios.slice()};

// 9. Ticking a box withdraws a pending «remove?».
_dcCatSel = new Set();
_dcCatAsk = true;
_dccatToggleOne('t1', true);
__o.tick = {sel: [..._dcCatSel], ask: _dcCatAsk};
_dcCatSel = new Set();

// 10. Sorting: a header click asks the server, again turns it round, and goes back to page 1.
reset();
_dcCatOff = 50;
__o.sortable = ['maker', 'model', 'u', 'kind', 'source', 'imported', 'ports', 'placed']
    .filter(k => html().includes(`_sortDcCat('${k}')`));
__o.sortDefault = /data-col="maker"[^>]*>(?:(?!<\/th>).)*bi-sort-up/s.test(html());
_sortDcCat('model');
await renderDcCat();
__o.sort1 = {asked: pedidos.slice(), up: /data-col="model"[^>]*>(?:(?!<\/th>).)*bi-sort-up/s.test(html())};
pedidos = [];
_sortDcCat('model');
await renderDcCat();
__o.sort2 = {asked: pedidos.slice(), down: /data-col="model"[^>]*>(?:(?!<\/th>).)*bi-sort-down/s.test(html()),
             url: _dcCatUrlQuery('list')};
_dcCatSort = '';
_dcCatDir = 'asc';
__o.urlDefault = _dcCatUrlQuery('list');
// A component's height is a size written as text: not sortable there.
_dcCatTree = 'component-types';
reset();
await renderDcCat();
__o.uComp = html().includes("_sortDcCat('u')");
_dcCatTree = '';

// 11. The page size: chosen, honoured by the server, saved per user; pages move the offset.
reset();
guardados = 0;
_changeDcCatPageSize('50');
await renderDcCat();
__o.size = {asked: pedidos.slice(), saved: guardados,
            extra: _LIST_TABLE_REGISTRY.find(d => d.k === 'dccat').extra()};
pedidos = [];
_goDcCatPage(2);
await renderDcCat();
__o.page2 = pedidos.slice();
_dcCatOff = 0;
// Back from what login says: a saved size returns, a size the server would not serve does not.
_applyUserTableConfig({dccat: {cols: ['maker', 'model'], order: [], ps: 100}});
__o.applied = {ps: _dccatPageSize, limit: _dcCatLimit()};
_applyUserTableConfig({dccat: {cols: ['maker', 'model'], order: [], ps: 5000}});
__o.appliedBad = _dccatPageSize;
_applyUserTableConfig({});

// 12. The columns: «placed» asks the server; one the page has does not.
reset();
_dccatToggleCol('placed');
await renderDcCat();
__o.placed = {asked: pedidos.some(a => a.split('&').includes('placed=1')),
              cell: html().includes('>3</td>'), sortable: html().includes("_sortDcCat('placed')")};
pedidos = [];
_dccatToggleCol('imported');
await renderDcCat();
__o.importedNoFetch = pedidos.length;
_dcCat = Object.assign({}, D, {usage: false});
_dcCat.args = _dcCatQueryArgs();
await renderDcCat();
__o.noUsage = {chooser: html().includes(`'_dccatToggleCol','placed'`),
               args: _dcCatQueryArgs().includes('placed=1')};
_applyUserTableConfig({});

// 13. A reader: the same card, no boxes, nothing that writes.
reset();
may.delete('dcim_catalog_manage');
await renderDcCat();
const hr = html();
__o.reader = {card: hr.includes('ss-card-header') && hr.includes('ss-card-band-top'),
              boxes: hr.includes('_dccatToggleOne(') || hr.includes('_dccatSelectAll('),
              writes: ['_dcCatEdit(null)', '_dcLibImportOpen()', 'bi-three-dots',
                       '_dcCatEmptySrc()', '_dcPortImport(', 'ss-th-actions', '_dcCatRowEdit(',
                       '_dcCatDrop(', '_dcPmOpen('].filter(x => hr.includes(x)),
              chooser: hr.includes('ss-col-chooser'), rows: hr.includes('_dcCatRowClick(')};
_dcLibModelDrawer('t1');
__o.readerDrawerDrop = cajon.a.includes('_dcLibModelDrop(');
may.add('dcim_catalog_manage');

// 14. «By brand» lives in the same card: no pages, no chooser, the cards of brands.
reset();
_dcCatView = 'makers';
await renderDcCat();
const hg = html();
__o.grid2 = {card: hg.includes('ss-card-header') && hg.includes('ss-card-tools'),
             cards: hg.includes('_dcCatPickMaker(&quot;Acme&quot;)'),
             noBands: !hg.includes('ss-card-band'), noChooser: !hg.includes('ss-col-chooser')};
_dcCatView = 'list';

// 15. Nothing matched: the card, its tools, and the way out.
_dcCat = Object.assign({}, D, {rows: [], total: 0});
_dcCat.args = _dcCatQueryArgs();
_dcCatQ = 'zzz';
_dcCat.args = _dcCatQueryArgs();
await renderDcCat();
const he = html();
__o.empty = {msg: he.includes(esc(t('dcim_lib_no_results'))),
             out: he.includes("_dcCatUnfilter('all')"), tools: he.includes('id="dccat-q"')};
_dcCatQ = '';

// 16. The header search: to Models, with only that written.
_dcCatTree = 'rack-types';
_dcCatImg = 'none';
_dcCatView = 'makers';
fui = [];
_dcLibSearch('  pm9a3 ');
__o.search = {q: _dcCatQ, tree: _dcCatTree, img: _dcCatImg, view: _dcCatView, went: fui};
_dcLibSearch('   ');
__o.searchEmpty = fui.length;

// 17. The grid keeps the filters; a card goes to the table of that brand.
_dcCatQ = 'sw';
_dcCatGoView('makers');
__o.grid = {view: _dcCatView, q: _dcCatQ};
const g = _dcCatMakersHtml(D);
__o.gridHtml = {acme: g.includes('_dcCatPickMaker(&quot;Acme&quot;)'),
                note: g.includes(esc(t('dcim_lib_grid_note')))};
abiertos = 0;
_dcCatPickMaker('Acme');
__o.pick = {maker: _dcCatMaker, view: _dcCatView, q: _dcCatQ, opened: abiertos};

// 18. Typing searches when the typing stops, not on every key.
const relojes = [];
setTimeout = (fn, ms) => { relojes.push(ms); return 7; };
_dcCatQType('ab');
__o.typed = {q: _dcCatQ, timers: relojes};
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
class TestTheChips:

    def test_each_filter_set_is_a_chip_and_two_can_go_at_once(self, out):
        assert out['chips'] == {'n': 9, 'all': True, 'brand': True, 'imp': True, 'q': True}

    def test_what_is_set_travels_to_the_server(self, out):
        a = out['args'].split('&')
        for p in ('offset=0', 'q=sw', 'kind=switch', 'tree=rack-types', 'brand_uid=b1',
                  'source=manual', 'img=none', 'ports=none', 'unused=1',
                  'import=library%402026-10-01T10%3A00%3A00Z',
                  'limit=25', 'sort=maker', 'dir=asc'):
            assert p in a, p

    def test_one_chip_takes_off_its_filter_and_remove_all_takes_them_all(self, out):
        assert out['unBrand'] == {'brand': '', 'kind': 'switch', 'opened': 1}
        assert out['unAll'] == '|||||||' and out['noChips']
        assert out['chipNone']

    def test_the_brand_select_offers_the_brands_with_models_and_no_record(self, out):
        assert out['brandSel'] == {'acme': True, 'borealis': False, 'none': True}


@_needs_node
class TestTheBand:

    def test_what_is_ticked_and_what_to_do_with_it(self, out):
        assert out['band'] == {'marked': True, 'export': True, 'untick': True, 'ask': True}

    def test_removing_asks_in_the_band_and_not_in_a_dialog(self, out):
        assert out['bandAsk'] == {'danger': True, 'go': True, 'question': True}
        assert out['dropped']['dialogs'] == 0
        assert out['dropped']['sent'] == [['POST', '/api/v1/dcim/catalog/drop',
                                          {'uids': ['t1', 't2']}]]

    def test_a_reader_has_no_band_and_untick_clears_every_page(self, out):
        assert out['bandReader'] == ''
        assert out['untickAll'] == 0

    def test_ticking_a_box_withdraws_a_pending_question(self, out):
        assert out['tick'] == {'sel': ['t1'], 'ask': False}


@_needs_node
class TestTheCard:
    """One card edge to edge, drawn by `createListTable` like Brands and Users: no title row
    of the library above it, the tools inside it, the pagination bands of every list."""

    def test_the_library_draws_no_title_row_for_the_models(self, out):
        assert '<div id="dccat-container" class="ss-vfill"></div>' in out['hole']
        assert out['card']['noTitleRow']

    def test_header_tools_bands_and_table_in_that_order(self, out):
        c = out['card']
        assert c['header'] and c['count'] and c['order']

    def test_the_header_buttons_in_their_order(self, out):
        assert out['card']['buttons'] and out['card']['more']

    def test_the_shapes_and_the_view_then_the_filters(self, out):
        assert out['card']['shapesThenFilters'] and out['card']['search']

    def test_the_chooser_offers_the_columns_but_not_the_thumbnail(self, out):
        """`model` is always on (its row is locked, no toggle); the thumbnail is not offered."""
        assert out['card']['chooserCols'] == ['maker', 'u', 'kind', 'ports', 'source',
                                              'placed', 'imported']
        assert out['card']['chooserLocked'] == 1, 'the thumbnail is offered in the chooser'

    def test_per_user_like_every_list(self, out):
        assert out['reg'] == {'def': ['kind', 'maker', 'model', 'ports', 'source', 'u'],
                              'label': 'dcim_cat_tab_list', 'extra': {'ps': 25}}

    def test_the_thumbnail_and_the_kind_stay(self, out):
        assert out['card']['thumb'] and out['card']['kindBadge']


@_needs_node
class TestThePages:

    def test_showing_top_and_bottom_and_the_size_selector(self, out):
        """25 by default, the panel's sizes up to what the server serves — and no «all»,
        which on six thousand models is a size the server refuses."""
        c = out['card']
        assert c['showing'] == 2
        assert c['sizes'] == ['15', '25*', '50', '100', '200'] and c['noAll']

    def test_a_size_is_asked_of_the_server_and_saved_per_user(self, out):
        s = out['size']
        assert s['asked'] and 'limit=50' in s['asked'][-1].split('&')
        assert 'offset=0' in s['asked'][-1].split('&')
        assert s['saved'] == 1 and s['extra'] == {'ps': 50}

    def test_the_next_page_moves_the_offset(self, out):
        assert out['page2'] and 'offset=50' in out['page2'][-1].split('&')

    def test_a_saved_size_comes_back_and_a_wrong_one_does_not(self, out):
        assert out['applied'] == {'ps': 100, 'limit': 100}
        assert out['appliedBad'] is None


@_needs_node
class TestSorting:

    def test_the_sortable_headers(self, out):
        """Only what the server sorts: «ports» is a JSON blob and «placed» is counted in memory
        over the inventory, neither a column it can ORDER BY."""
        assert out['sortable'] == ['maker', 'model', 'u', 'kind', 'source']
        assert out['sortDefault'], 'the default order (by brand) is not shown on its header'

    def test_a_click_asks_the_server_and_goes_back_to_page_one(self, out):
        a = out['sort1']['asked'][-1].split('&')
        assert 'sort=model' in a and 'dir=asc' in a and 'offset=0' in a
        assert out['sort1']['up']

    def test_again_turns_it_round_and_the_address_says_so(self, out):
        a = out['sort2']['asked'][-1].split('&')
        assert 'sort=model' in a and 'dir=desc' in a
        assert out['sort2']['down']
        assert out['sort2']['url'] == 'sort=model&dir=desc'
        assert out['urlDefault'] == '', 'the default order wrote itself into the address'

    def test_a_components_size_is_not_sortable(self, out):
        assert out['uComp'] is False


@_needs_node
class TestRowsAndRemoving:

    def test_rows_have_their_actions_and_open_the_drawer(self, out):
        """Edit, clone and delete on every row, as the table had them and every list of the
        panel has them; the drawer has them too."""
        assert out['rows'] == {'actions': True, 'place': True, 'sameWidth': True, 'click': True,
                               'checks': 2, 'noSheet': True}
        assert out['rowClick'] == 'Acme SW-48'

    def test_the_box_and_its_cell_do_not_open_the_drawer(self, out):
        assert out['boxClick'] is None and out['cellClick'] is None

    def test_one_model_is_removed_from_its_drawer_asking_first(self, out):
        assert out['drawerDrop']
        d = out['drop']
        assert d['dialogs'] == 1 and d['asked'] and d['closed'] >= 1
        assert d['sent'] == [['DELETE', '/api/v1/dcim/catalog/t1', None]]

    def test_a_reader_sees_the_card_without_boxes_or_writes(self, out):
        r = out['reader']
        assert r['card'] and r['chooser'] and r['rows']
        assert r['boxes'] is False and r['writes'] == []
        assert out['readerDrawerDrop'] is False


@_needs_node
class TestTheColumns:

    def test_placed_asks_the_server(self, out):
        p = out['placed']
        assert p['asked'] and p['cell'] and p['sortable'] is False
        assert out['importedNoFetch'] == 0, 'a column the page already has was fetched again'

    def test_placed_is_not_offered_without_the_inventory(self, out):
        assert out['noUsage'] == {'chooser': False, 'args': False}


@_needs_node
class TestTheRowsTheSearchAndTheGrid:

    def test_by_brand_is_drawn_in_the_same_card(self, out):
        assert out['grid2'] == {'card': True, 'cards': True, 'noBands': True,
                                'noChooser': True}

    def test_nothing_matched_keeps_the_tools_and_the_way_out(self, out):
        assert out['empty'] == {'msg': True, 'out': True, 'tools': True}

    def test_the_header_search_goes_to_the_models_with_only_that(self, out):
        assert out['search'] == {'q': 'pm9a3', 'tree': '', 'img': '', 'view': 'list',
                                 'went': ['models']}
        assert out['searchEmpty'] == 1, 'an empty search went somewhere'

    def test_the_grid_keeps_the_filters_and_a_card_goes_to_its_brand(self, out):
        assert out['grid'] == {'view': 'makers', 'q': 'sw'}
        assert out['gridHtml'] == {'acme': True, 'note': True}
        assert out['pick'] == {'maker': 'Acme', 'view': 'list', 'q': 'sw', 'opened': 1}

    def test_typing_searches_when_the_typing_stops(self, out):
        assert out['typed']['q'] == 'ab' and out['typed']['timers'] == [450]
