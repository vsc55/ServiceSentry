#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalogue › Library as a section with VIEWS, each an address of its own.

It was a sidebar entry with a row of in-page tabs (brands, models, platforms, connectors,
schemas, import) and no address for any of them. Now it is a declared page (`HOME_PAGES`, id
`models`, placed in the Catalogue group) whose views the sidebar unfolds:

* `/catalog/library/<view>` for Summary, Brands, Models, Platforms, Connectors and Schemas —
  Schemas with a permission of its own (`dcim_catalog_manage`), enforced by the route, hidden
  by the sidebar and skipped by the client when it picks a view;
* the menu's entry keeps its reorder key (`t:models`) and carries a count beside each view;
* the old links (`/admin?tab=models&ctab=…`, `/dcim/catalog?ctab=…`) land on their view, with
  the rest of their query;
* moving between views pushes an address with that view's own state, and Back/Forward between
  two views of the open section redraws it (it did not, for any section with views).
"""

from __future__ import annotations

import io
import json
import os
import re
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

VIEWS = ['summary', 'brands', 'models', 'platforms', 'connectors', 'schemas']


def _as(admin, username, perms):
    """A session holding exactly *perms*, through a role of its own."""
    from tests.integration.test_wa_dcim import _as as _dcim_as      # noqa: PLC0415
    return _dcim_as(admin, username, perms)


# ── The declaration and the server ─────────────────────────────────────────────────────────

class TestTheDeclaration:

    def test_a_page_in_the_catalogue_with_six_views(self):
        from lib.web_admin.constants import standalone_page
        page = standalone_page('models')
        sa = page['standalone']
        assert page['url'] == '/catalog/library'
        assert (sa['placement'], sa['perm'], sa['pane'], sa['render']) == \
            ('catalog', 'dcim_catalog_view', 'tab-models', 'renderDcLibrary')
        assert [v['slug'] for v in sa['views']] == VIEWS

    def test_only_the_schemas_ask_for_more_than_the_section(self):
        from lib.web_admin.constants import standalone_page
        perms = {v['slug']: v.get('perm', '') for v in standalone_page('models')['standalone']
                 ['views']}
        assert perms.pop('schemas') == 'dcim_catalog_manage'
        assert set(perms.values()) == {''}

    def test_it_is_not_a_panel_tab_any_more(self):
        """Two entries with the same id would be two menu items opening the same pane."""
        from lib.web_admin.constants import PANEL_TABS
        assert 'models' not in [t['id'] for t in PANEL_TABS]

    def test_each_view_is_a_landing_page(self):
        from lib.web_admin.constants import landing_pages
        ids = {p['id'] for p in landing_pages()}
        assert {f'models/{v}' for v in VIEWS} <= ids


class TestTheRoutes:

    def test_every_view_is_an_address(self, client):
        _login(client)
        for slug in VIEWS:
            assert client.get(f'/catalog/library/{slug}').status_code == 200, slug
        assert client.get('/catalog/library').status_code == 200

    def test_a_view_with_its_own_permission_sends_a_reader_to_the_section(self, admin):
        lector = _as(admin, 'lector', ['dcim_catalog_view'])
        r = lector.get('/catalog/library/schemas')
        assert r.status_code == 302 and r.headers['Location'].endswith('/catalog/library')
        assert lector.get('/catalog/library/brands').status_code == 200
        gestor = _as(admin, 'gestor', ['dcim_catalog_view', 'dcim_catalog_manage'])
        assert gestor.get('/catalog/library/schemas').status_code == 200

    def test_without_the_section_permission_no_view_opens(self, admin):
        nadie = _as(admin, 'nadie', ['dcim_view'])
        r = nadie.get('/catalog/library/brands')
        assert r.status_code == 302 and '/catalog/library' not in r.headers['Location']


class TestTheSidebar:

    @pytest.fixture()
    def html(self, client):
        _login(client)
        return client.get('/admin').get_data(as_text=True)

    def _li(self, html, slug):
        i = html.index(f'data-subtab="#view-models-{slug}"')
        return html[html.rindex('<li', 0, i):i]

    def test_the_entry_keeps_its_reorder_key(self, html):
        """A reader who moved «Library» in their menu keeps it where they put it."""
        li = re.search(r'<li[^>]*id="tab-models-li"[^>]*>', html).group(0)
        assert 'data-sb-key="t:models"' in li and 'data-nav-perm="dcim_catalog_view"' in li
        assert 'data-nav-url="/catalog/library"' in html

    def test_a_view_with_a_permission_is_hidden_until_the_pass_reveals_it(self, html):
        schemas = self._li(html, 'schemas')
        assert 'data-nav-perm="dcim_catalog_manage"' in schemas and 'display:none' in schemas
        assert 'data-nav-perm' not in self._li(html, 'brands')

    def test_each_view_has_a_place_for_its_count(self, html):
        for slug in VIEWS:
            assert f'data-sb-vcount="models-{slug}"' in html, slug

    def test_the_client_spec_carries_each_views_permission(self, html):
        crudo = re.search(r'window\.SS_STANDALONE_PAGES = (\[.*?\]);\n', html).group(1)
        lib = [p for p in json.loads(crudo) if p['id'] == 'models'][0]
        assert {v['slug']: v['perm'] for v in lib['views']}['schemas'] == 'dcim_catalog_manage'


# ── The client, in node ────────────────────────────────────────────────────────────────────

_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
// The address, kept as a browser keeps it.
let __pushes = [];
function __go(u) {
    const x = new URL(String(u), 'http://x');
    window.location.pathname = x.pathname;
    window.location.search = x.search;
}
window.history = {replaceState: (s, tt, u) => __go(u),
                  pushState: (s, tt, u) => { __pushes.push(String(u)); __go(u); }};
_sbHighlightSub = () => {};
let abiertos = 0;
_dcCatOpen = async () => { abiertos++; };
const _realRender = renderDcim;
let pintado = 0;
renderDcim = () => { pintado++; };
const may = new Set(['dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
// A pane that is open, or not.
let __abierto = false;
const _getReal = document.getElementById;
document.getElementById = (id) => id === 'tab-models'
    ? {classList: {contains: (c) => c === 'active' && __abierto}} : _getReal(id);

// 1. The old links, to their view, with the rest of their query.
const migra = (path, search) => {
    window.location.pathname = path;
    window.location.search = search;
    _dcLibMigrate();
    return window.location.pathname + window.location.search;
};
localStorage.removeItem('ss_active_view_models');
__o.old = {
    brands: migra('/admin', '?tab=models&ctab=brands&bview=usage'),
    conns: migra('/admin', '?tab=models&ctab=conns'),
    list: migra('/dcim/catalog', '?ctab=list&tree=rack-types&q=42U'),
    // Another view remembered, so that landing on the models is the rule and not the memory.
    filtersOnly: (localStorage.setItem('ss_active_view_models', 'brands'),
                  migra('/admin', '?tab=models&tree=component-types')),
    onLibrary: migra('/catalog/library/platforms', '?eos=gone'),
};
_dcLibImportWanted = false;
__o.importUrl = migra('/admin', '?tab=models&ctab=import');
__o.importWanted = _dcLibImportWanted;
may.delete('dcim_catalog_manage');
_dcLibImportWanted = false;
migra('/admin', '?tab=models&ctab=import');
__o.importWantedReader = _dcLibImportWanted;
may.add('dcim_catalog_manage');
localStorage.setItem('ss_active_view_models', 'platforms');
__o.bare = migra('/admin', '?tab=models');

// 2. Which view: the address, then the last used, then the first — of those the reader may open.
currentUser = {permissions: ['dcim_catalog_view']};
window.location.search = '';
window.location.pathname = '/catalog/library/schemas';
localStorage.setItem('ss_active_view_models', 'platforms');
__o.readerUrl = _sbPageView('models');
localStorage.setItem('ss_active_view_models', 'schemas');
// (A path the harness can walk: its `?.`-free copy of `_sbSectionOf` trips on a bare section.)
window.location.pathname = '/catalog/library/nonsense';
__o.readerSaved = _sbPageView('models');
currentUser = {permissions: ['dcim_catalog_view', 'dcim_catalog_manage']};
window.location.pathname = '/catalog/library/schemas';
__o.managerUrl = _sbPageView('models');
may.delete('dcim_catalog_manage');
_dcCatTab = 'schemas';
__o.tabNowReader = _dcLibTabNow();
may.add('dcim_catalog_manage');
__o.tabNowManager = _dcLibTabNow();

// 3. The entry point: the view from the address. The models are asked to the server; the
//    other views paint with what there is.
_dcLibBooted = true;
_dcLibLastUrl = '';
_dcCat = {rows: [], counts: {}};
window._ssNavPicked = {pageId: 'models', slug: 'brands'};
window.location.pathname = '/catalog/library/brands';
abiertos = 0; pintado = 0;
renderDcLibrary();
__o.r1 = {tab: _dcCatTab, opened: abiertos, painted: pintado,
          saved: localStorage.getItem('ss_active_view_models'),
          picked: window._ssNavPicked};
window._ssNavPicked = {pageId: 'models', slug: 'models'};
window.location.pathname = '/catalog/library/models';
abiertos = 0;
renderDcLibrary();
__o.r2 = {tab: _dcCatTab, opened: abiertos};

// 4. Moving inside the library: an address with THAT view's state, pushed.
__abierto = true;
_dcCatFiltersReset();
_dcCatTree = 'rack-types';
_dcCatQ = '42U';
_dcBrandView = 'usage';
__pushes = [];
_dcLibGo('models');
_dcLibGo('brands');
__o.go = {pushes: __pushes.slice(), last: _dcLibLastUrl, tab: _dcCatTab};
// From outside the library, through the menu's own door.
__abierto = false;
let puerta = null;
const _nav = _navPageView;
_navPageView = (p, s) => { puerta = [p, s]; };
_dcLibGo('platforms');
__o.outside = puerta;
_navPageView = _nav;
__abierto = true;

// 5. Back: the address differs from the last one written, so the address wins — its filters,
//    and the defaults for what it does not say.
_dcBrandView = 'usage';
_dcCatQ = 'stale';
window.location.pathname = '/catalog/library/models';
window.location.search = '?tree=module-types';
window._ssNavPicked = null;
renderDcLibrary();
__o.back = {tab: _dcCatTab, tree: _dcCatTree, q: _dcCatQ, bview: _dcBrandView};
// A menu click keeps what is set, and only rewrites the query.
_dcCatQ = 'kept';
window._ssNavPicked = {pageId: 'models', slug: 'models'};
window.location.search = '';
renderDcLibrary();
__o.picked = {q: _dcCatQ};

// 6. The address of a view says only what is that view's.
_dcCatFiltersReset();
_dcCatTree = 'rack-types';
_dcBrandView = 'trees';
_dcPlatEos = 'soon';
__o.urls = {models: _dcLibUrl('models'), brands: _dcLibUrl('brands'),
            platforms: _dcLibUrl('platforms'), summary: _dcLibUrl('summary')};
_dcBrandView = 'table';
_dcPlatEos = '';
// …and nothing is written while somebody is elsewhere.
window.location.pathname = '/overview';
window.location.search = '';
_dcCatUrlSave();
__o.elsewhere = window.location.pathname;

// 7. The counts beside each view, in the sidebar.
const vc = {};
const _qsReal = document.querySelector;
document.querySelector = (sel) => {
    const m = String(sel).match(/data-sb-vcount="([^"]+)"/);
    if (m) return (vc[m[1].replace(/\\/g, '')] = vc[m[1].replace(/\\/g, '')]
                   || {textContent: ''});
    return _qsReal(sel);
};
_dcCat = {counts: {models: 212, brands: 20, platforms: 5, connectors: 131, schemas: 3}};
_dcLibCounts();
__o.counts = Object.fromEntries(Object.entries(vc).map(([k, v]) => [k, v.textContent]));

// 8. Back/Forward between two views of the section already on screen redraws it.
let vistas = [];
const _rmpv = renderModulePageView;
renderModulePageView = (id) => { vistas.push(id); };
document.querySelector = (sel) => String(sel).includes('data-bs-target="#tab-models"')
    ? {closest: () => ({style: {display: ''}})} : _qsReal(sel);
__abierto = true;
window.location.pathname = '/catalog/library/brands';
_sbActivateFromLocation();
__o.popSame = vistas.slice();
__abierto = false;
vistas = [];
_sbActivateFromLocation();
__o.popOther = vistas.slice();
renderModulePageView = _rmpv;
document.querySelector = _qsReal;

// 9. The inventory's old address for the catalogue keeps its query on the way.
__abierto = false;
document.getElementById = (id) => (id === 'tab-models' || id === 'tab-builds')
    ? {classList: {contains: () => false}} : _getReal(id);
let navegado = '';
const _nt = _navTab;
_navTab = (x) => { navegado = x; };
window.location.pathname = '/dcim/catalog';
window.location.search = '?ctab=brands&bview=usage';
await _realRender();
__o.moved = {url: window.location.pathname + window.location.search, nav: navegado};
_navTab = _nt;
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
class TestTheOldLinks:

    def test_each_tab_lands_on_its_view_with_the_rest_of_its_query(self, out):
        o = out['old']
        assert o['brands'] == '/catalog/library/brands?bview=usage'
        assert o['conns'] == '/catalog/library/connectors'
        assert o['list'] == '/catalog/library/models?tree=rack-types&q=42U'

    def test_a_models_filter_without_a_tab_is_the_models(self, out):
        """`models` was the tab a link without `ctab` opened."""
        assert out['old']['filtersOnly'] == '/catalog/library/models?tree=component-types'

    def test_an_address_of_the_library_is_left_alone(self, out):
        assert out['old']['onLibrary'] == '/catalog/library/platforms?eos=gone'

    def test_the_import_tab_opens_the_models_with_the_import_box(self, out):
        assert out['importUrl'] == '/catalog/library/models'
        assert out['importWanted'] is True
        assert out['importWantedReader'] is False, 'a reader cannot import'

    def test_a_bare_old_link_opens_the_view_used_last(self, out):
        assert out['bare'] == '/catalog/library/platforms'


@_needs_node
class TestWhichView:

    def test_a_reader_never_lands_on_the_schemas(self, out):
        assert out['readerUrl'] == 'platforms', 'the address won over the permission'
        assert out['readerSaved'] == 'summary', 'the remembered view won over the permission'
        assert out['managerUrl'] == 'schemas'
        assert out['tabNowReader'] == 'summary' and out['tabNowManager'] == 'schemas'

    def test_the_entry_point_draws_the_view_the_address_names(self, out):
        assert out['r1'] == {'tab': 'brands', 'opened': 0, 'painted': 1, 'saved': 'brands',
                             'picked': None}
        assert out['r2'] == {'tab': 'list', 'opened': 1}

    def test_going_to_a_view_pushes_its_address_with_its_state(self, out):
        assert out['go']['pushes'] == ['/catalog/library/models?tree=rack-types&q=42U',
                                       '/catalog/library/brands?bview=usage']
        assert out['go']['last'] == '/catalog/library/brands?bview=usage'
        assert out['go']['tab'] == 'brands'

    def test_from_outside_the_library_it_goes_through_the_menu(self, out):
        assert out['outside'] == ['models', 'platforms']

    def test_back_reads_the_address_and_a_menu_click_keeps_the_state(self, out):
        assert out['back'] == {'tab': 'list', 'tree': 'module-types', 'q': '', 'bview': 'table'}
        assert out['picked'] == {'q': 'kept'}

    def test_each_view_writes_only_its_own_state(self, out):
        assert out['urls'] == {'models': '/catalog/library/models?tree=rack-types',
                               'brands': '/catalog/library/brands?bview=trees',
                               'platforms': '/catalog/library/platforms?eos=soon',
                               'summary': '/catalog/library/summary'}
        assert out['elsewhere'] == '/overview', 'a late answer rewrote another section\'s URL'


@_needs_node
class TestTheMenu:

    def test_each_view_shows_its_count(self, out):
        assert out['counts'] == {'models-brands': '20', 'models-models': '212',
                                 'models-platforms': '5', 'models-connectors': '131',
                                 'models-schemas': '3'}

    def test_back_between_two_views_of_the_open_section_redraws_it(self, out):
        assert out['popSame'] == ['models']
        assert out['popOther'] == [], 'a section not on screen is opened, not redrawn'

    def test_the_inventorys_old_catalogue_address_keeps_its_query(self, out):
        assert out['moved'] == {'url': '/catalog/library?ctab=brands&bview=usage',
                                'nav': '#tab-models'}
