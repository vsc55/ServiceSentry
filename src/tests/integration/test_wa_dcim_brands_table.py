#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The DCIM catalogue's «Brands» tab, drawn by the panel's shared list table.

The tab drew a hand-built table: fixed headers, no column chooser, no sorting, no pagination,
and none of the audit columns the brand rows carry since day one. It now goes through
`createListTable` like its sibling «Templates», under the per-user key `dcbrd`.

The probe runs the real panel bundle in `node`: the table is rendered into a fake container
and its HTML is read back — what is declared, and what a person would see and click.
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


# ── The server: what the rows carry ────────────────────────────────────────────────────────

class TestTheRowsCarryWhatTheTableShows:

    def test_a_brand_row_carries_uid_and_the_three_audit_fields(self, client):
        """The meta columns read the row itself (`record: b => b`): if the API stopped
        sending them, the columns would sit in the chooser with empty cells."""
        _login(client)
        assert client.post('/api/v1/dcim/brands',
                           json={'name': 'Acme Redes', 'account': 'C-1'}).status_code == 200
        fila = client.get('/api/v1/dcim/brands').get_json()['brands'][0]
        for k in ('uid', 'name', 'description', 'url', 'support_url', 'account', 'models',
                  'created_at', 'updated_at', 'updated_by'):
            assert k in fila, k
        assert fila['created_at'] and fila['updated_by']


# ── The panel: the table, in node ──────────────────────────────────────────────────────────

_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
// A container that behaves: it remembers its HTML, and the filter bar's body is a real node
// once the factory has written the shell (the harness' getElementById hands out a fresh,
// forgetful node per call — a table drawn there is a table nobody can read).
function caja() {
    const body = {innerHTML: '', classList: {add() {}}};
    const c = {innerHTML: '', body,
        classList: {_s: [], add(x) { this._s.push(x); }, contains(x) { return this._s.includes(x); }},
        querySelector(sel) {
            if (sel === '.ss-filterbar') return c.innerHTML.includes('ss-filterbar') ? {} : null;
            if (sel === '.ss-lt-body') return c.innerHTML.includes('ss-lt-body') ? body : null;
            return null;
        }};
    return c;
}
let cont = caja();
let filtro = '';
const _getReal = document.getElementById;
document.getElementById = (id) => {
    if (id === 'dcbrd-container') return cont;
    if (id === 'dcbrdFQ') return {value: filtro};
    return _getReal(id);
};
let puede = true;
_dcimMay = (p) => p === 'dcim_catalog_manage' && puede;
const html = () => cont.body.innerHTML;
// The uids of the drawn rows, in order, read from each row's click.
const filas = () => [...html().matchAll(/<tr class="ss-rowlink" onclick="([^"]*)"/g)]
    .map(m => m[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&'));
const uids = () => filas().map(f => JSON.parse('[' + f.slice(f.indexOf('(') + 1, -1) + ']')[0]);

const ROWS = [
    {uid: 'b1', name: 'Acme Redes', description: 'conmutadores', models: 2,
     url: 'https://acme.example', support_url: '', account: 'C-001', platforms: 10,
     created_at: '2026-01-01 10:00:00', updated_at: '2026-02-01 10:00:00', updated_by: 'ana'},
    {uid: 'b2', name: 'Borealis', description: '', models: 10, url: '', platforms: 2,
     support_url: 'https://soporte.borealis.example', account: '',
     created_at: '', updated_at: '', updated_by: ''},
    {uid: 'b3', name: 'Cumulus', description: '', models: 0, url: '', support_url: '', platforms: 0,
     account: 'X-9', created_at: '', updated_at: '', updated_by: ''},
];

// 1. Registered in the per-user persistence registry, with its columns.
const reg = _LIST_TABLE_REGISTRY.find(d => d.k === 'dcbrd');
__o.reg = !!reg;
__o.cols = reg ? reg.all().map(c => c.id) : [];
__o.def = reg ? [...reg.def()].sort() : [];
__o.clearLabel = reg ? reg.clearLabelKey : '';
__o.renderFn = typeof renderDcBrd === 'function';
// What login does: a table the user never customised starts with its default columns.
_applyUserTableConfig({});

// 2. The tab leaves the hole and the catalogue's drawing fills it.
_dcCatTab = 'brands';
_dcBrands = {rows: ROWS.slice()};
__o.hole = _dcBrandsHtml();
_dcCat = {rows: [], total: 0, counts: {}};
const models = {innerHTML: '', classList: {contains: () => true}};
document.getElementById = ((prev) => (id) => id === 'models-container' ? models : prev(id))(
    document.getElementById);
await _dcimRenderApart('models');
// Not `renderDcBrd()` by hand: what is checked is that the catalogue's drawing calls it. Its
// render is async (`prepare` awaits), so let the microtasks run.
for (let i = 0; i < 50; i++) await Promise.resolve();
__o.modelsPaneHasHole = models.innerHTML.includes('id="dcbrd-container"');
__o.drawnAfterApart = html().includes('id="dcbrd-table"');
const h1 = html();
__o.withManage = {
    actionsHeader: h1.includes('ss-th-actions'),
    edit: h1.includes('_dcBrandEdit('), drop: h1.includes('_dcBrandDrop('),
    newBtn: h1.includes('_dcBrandEdit(null)'),
    intro: h1.includes(t('dcim_brand_intro')),
    sortModels: h1.includes("_sortDcBrd('models')"),
    sortPlats: h1.includes("_sortDcBrd('platforms')"),
    platsRight: /<th class="ss-th ss-th-resizable text-end" data-col="platforms"/.test(h1),
    modelsRight: /<th class="ss-th ss-th-resizable text-end" data-col="models"/.test(h1),
    desc: h1.includes('conmutadores'),
    link: h1.includes('href="https://acme.example"'),
    support: h1.includes('href="https://soporte.borealis.example"'),
    account: h1.includes('C-001'),
    uidHidden: !h1.includes('data-col="uid"') && !h1.includes('data-col="created_at"'),
    card: h1.includes('ss-card') && h1.includes('ss-card-header'),
};
__o.order0 = uids();

// 3. Sorting by models is numeric: as text, 10 would sit between 0 and 2.
_sortDcBrd('models');
await renderDcBrd();
__o.byModels = uids();
_sortDcBrd('models');
await renderDcBrd();
__o.byModelsDesc = uids();
_sortDcBrd('name');
_dcbrSortDir = 'asc';

// Platforms sort as numbers too.
_sortDcBrd('platforms');
await renderDcBrd();
__o.byPlats = uids();
_sortDcBrd('name');
_dcbrSortDir = 'asc';

// 4. Pagination: two per page, three rows.
_changeDcBrdPageSize('2');
await renderDcBrd();
__o.page1 = uids();
_goDcBrdPage(2);
await renderDcBrd();
__o.page2 = uids();
_changeDcBrdPageSize('25');
await renderDcBrd();

// 5. The row goes to that brand's models, by uid.
let abierto = 0;
_dcCatOpen = () => { abierto++; };
const clic = filas().find(f => f.includes('"b2"'));
eval(clic);
__o.go = {tab: _dcCatTab, view: _dcCatView, brand: _dcCatBrand, name: _dcCatBrandName,
          opened: abierto};
_dcCatTab = 'brands';

// 6. The filter bar narrows by name, description or account.
filtro = 'x-9';
_ltFilterChanged_dcbrd();
await renderDcBrd();
__o.filtered = uids();
filtro = 'nadie';
_ltFilterChanged_dcbrd();
await renderDcBrd();
__o.filteredNone = html().includes(t('no_filter_matches'));
filtro = '';
_ltFilterClear_dcbrd();
await renderDcBrd();
__o.unfiltered = uids();

// 7. Without the manage permission: no actions column, no buttons, the row still links.
puede = false;
await renderDcBrd();
const h2 = html();
__o.noManage = {actionsHeader: h2.includes('ss-th-actions'), edit: h2.includes('_dcBrandEdit('),
                drop: h2.includes('_dcBrandDrop('), rows: uids().length};

// 8. Empty: the card stays, with its message and (with permission) the button to create one.
puede = true;
_dcBrands = {rows: []};
await renderDcBrd();
const h3 = html();
__o.empty = {msg: h3.includes(t('dcim_brand_none')), newBtn: h3.includes('_dcBrandEdit(null)'),
             card: h3.includes('ss-card-header')};

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
    wa = WebAdmin(cfg, 'admin', 'secret', var,
                  pw_require_upper=False, pw_require_digit=False)
    wa._csrf_enabled = False
    wa.app.config['TESTING'] = True
    c = wa.app.test_client()
    _login(c)
    res = node_run(panel_bundle(c), _PROBE)
    assert not res.get('fallo'), res.get('fallo')
    return res


@_needs_node
class TestTheTabIsTheSharedListTable:

    def test_registered_for_per_user_persistence(self, out):
        """`persist: true` puts it in `_LIST_TABLE_REGISTRY`, which is what the per-user
        table config and the Customisations list read — no literal to keep in sync."""
        assert out['reg'], 'the brands table is not in the list-table registry'
        assert out['renderFn']
        assert out['clearLabel'] == 'dcim_cat_tab_brands'

    def test_its_columns_and_the_shared_meta_ones_hidden_by_default(self, out):
        assert out['cols'] == ['name', 'models', 'platforms', 'url', 'support', 'account',
                               'uid', 'created_at', 'updated_at', 'updated_by']
        assert out['def'] == ['account', 'models', 'platforms', 'support', 'url']
        assert out['withManage']['uidHidden']

    def test_the_tab_leaves_a_hole_and_the_catalogue_fills_it(self, out):
        """The container only exists once the pane is written: the catalogue's drawing must
        fill it afterwards, or the tab is blank without a single error."""
        assert '<div id="dcbrd-container" class="ss-vfill"></div>' in out['hole']
        assert out['modelsPaneHasHole']
        assert out['drawnAfterApart'], 'drawing the catalogue does not draw the brands table'

    def test_what_a_row_shows(self, out):
        w = out['withManage']
        assert w['card'] and w['intro']
        assert w['desc'] and w['link'] and w['support'] and w['account']


@_needs_node
class TestSortingAndPages:

    def test_by_name_first(self, out):
        assert out['order0'] == ['b1', 'b2', 'b3']

    def test_models_sort_as_numbers(self, out):
        """As text, 10 sorts between 0 and 2."""
        assert out['withManage']['sortModels']
        assert out['byModels'] == ['b3', 'b1', 'b2']
        assert out['byModelsDesc'] == ['b2', 'b1', 'b3']

    def test_the_models_header_is_right_aligned(self, out):
        assert out['withManage']['modelsRight']

    def test_platforms_have_their_own_numeric_column(self, out):
        """Not added to «Models»: a platform is catalogue of the brand, not a model."""
        assert out['withManage']['sortPlats'] and out['withManage']['platsRight']
        assert out['byPlats'] == ['b3', 'b2', 'b1']

    def test_paginates(self, out):
        assert out['page1'] == ['b1', 'b2'] and out['page2'] == ['b3']


@_needs_node
class TestClicksAndPermission:

    def test_a_row_opens_that_brands_models(self, out):
        assert out['go'] == {'tab': 'list', 'view': 'list', 'brand': 'b2', 'name': 'Borealis',
                             'opened': 1}

    def test_with_manage_edit_delete_and_new(self, out):
        w = out['withManage']
        assert w['actionsHeader'] and w['edit'] and w['drop'] and w['newBtn']

    def test_without_manage_no_actions_but_rows(self, out):
        n = out['noManage']
        assert not n['actionsHeader'] and not n['edit'] and not n['drop']
        assert n['rows'] == 3


@_needs_node
class TestFilterAndEmpty:

    def test_the_filter_bar_narrows_by_name_description_or_account(self, out):
        assert out['filtered'] == ['b3']
        assert out['filteredNone']
        assert out['unfiltered'] == ['b1', 'b2', 'b3']

    def test_empty_keeps_the_card_and_the_new_button(self, out):
        e = out['empty']
        assert e['msg'] and e['card'] and e['newBtn']
