#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The DCIM catalogue's «Brands» tab: its three views and the data two of them need.

Table (the default, `test_wa_dcim_brands_table.py`), In use in the installation, and By model
type. The view travels in the address (`bview`), like the Models
tab's own view, so a reload or a shared link reopens the same one.

Two of them need what the brands list did not carry:

* **by model type** — each brand's models split by tree, from one `GROUP BY`;
* **in use** — how many placed items, distinct models, racks and sites, asked for with
  `?usage=1` and **counted over what the caller may see**: the inventory's company boundary
  applies, and a reader without `dcim_view` gets no counts at all (the brands list is read with
  the catalogue's permission, and placed items are the inventory's business).
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


def _by_name(client, url='/api/v1/dcim/brands'):
    d = client.get(url).get_json()
    return d, {b['name']: b for b in d['brands']}


# ── The server ─────────────────────────────────────────────────────────────────────────────

class TestModelsByTree:

    def test_each_brand_carries_its_models_split_by_tree(self, client):
        _login(client)
        c = client
        c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'A1'})
        c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'A2'})
        c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'DIMM-8',
                                             'tree': 'component-types', 'kind': 'memory'})
        c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Borealis', 'model': 'R42',
                                             'tree': 'rack-types'})
        c.post('/api/v1/dcim/brands', json={'name': 'Cumulus'})
        _d, m = _by_name(c)
        assert m['Acme']['trees'] == {'device-types': 2, 'component-types': 1}
        assert m['Acme']['models'] == 3
        assert m['Borealis']['trees'] == {'rack-types': 1}
        assert m['Cumulus']['trees'] == {}

    def test_and_its_platforms_counted_apart(self, client):
        """A brand that only makes systems has no model and is still part of the catalogue."""
        _login(client)
        c = client
        c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'A1'})
        sistemas = _uid(c.post('/api/v1/dcim/brands', json={'name': 'Sistemas Norte'}))
        acme = [b for b in c.get('/api/v1/dcim/brands').get_json()['brands']
                if b['name'] == 'Acme'][0]['uid']
        for nombre, marca in (('NorteOS 1', sistemas), ('NorteOS 2', sistemas),
                              ('AcmeOS', acme)):
            assert c.post('/api/v1/dcim/platforms',
                          json={'name': nombre, 'brand_uid': marca}).status_code == 200
        _d, m = _by_name(c)
        assert (m['Sistemas Norte']['models'], m['Sistemas Norte']['platforms']) == (0, 2)
        assert (m['Acme']['models'], m['Acme']['platforms']) == (1, 1)


@pytest.fixture()
def fleet(client, admin):
    """Two companies with a site, room and rack each, and items of two brands placed in both."""
    _login(client)
    c = client
    org = lambda n: _uid(c.post('/api/v1/orgs', json={'name': n, 'short': n}))  # noqa: E731
    a, b = org('A'), org('B')
    racks = {}
    for nombre, empresa in (('SA', a), ('SB', b)):
        site = _uid(c.post('/api/v1/dcim/sites', json={'name': nombre}))
        c.post('/api/v1/orgs/owner', json={'scope': 'site', 'uid': site, 'org_uid': empresa})
        room = _uid(c.post('/api/v1/dcim/rooms', json={'site_uid': site, 'name': 'R'}))
        racks[nombre] = _uid(c.post('/api/v1/dcim/racks', json={'room_uid': room, 'name': 'K',
                                                                'u_height': 42}))
    t1 = _uid(c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'A1'}))
    t2 = _uid(c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Acme', 'model': 'A2'}))
    t3 = _uid(c.post('/api/v1/dcim/catalog', json={'manufacturer': 'Borealis', 'model': 'B1'}))
    u = [0]

    def item(rack, tipo):
        u[0] += 1
        return _uid(c.post('/api/v1/dcim/items', json={'rack_uid': racks[rack], 'u_start': u[0],
                                                       'u_height': 1, 'label': f'i{u[0]}',
                                                       'type_uid': tipo}))
    item('SA', t1)
    item('SA', t1)
    item('SA', t2)
    item('SB', t3)
    item('SB', t1)
    # One with no model: it is nobody's brand, and is not counted.
    c.post('/api/v1/dcim/items', json={'rack_uid': racks['SA'], 'u_start': 30, 'u_height': 1,
                                       'label': 'blank'})
    return {'a': a, 'b': b, 'admin': admin}


class TestInUse:

    def test_only_when_asked(self, client, fleet):
        d, m = _by_name(client)
        assert d['usage'] is False and 'in_use' not in m['Acme']

    def test_the_whole_fleet_for_who_sees_every_company(self, client, fleet):
        d, m = _by_name(client, '/api/v1/dcim/brands?usage=1')
        assert d['usage'] is True
        assert m['Acme']['in_use'] == {'items': 4, 'models': 2, 'racks': 2, 'sites': 2}
        assert m['Borealis']['in_use'] == {'items': 1, 'models': 1, 'racks': 1, 'sites': 1}

    def test_another_companys_items_are_not_counted(self, client, fleet):
        """Company A's reader: B's two items —an Acme and the only Borealis— do not exist."""
        ua = _as(fleet['admin'], 'ua', ['dcim_view', 'dcim_catalog_view',
                                        f'org.{fleet["a"]}.view'])
        d, m = _by_name(ua, '/api/v1/dcim/brands?usage=1')
        assert d['usage'] is True
        assert m['Acme']['in_use'] == {'items': 3, 'models': 2, 'racks': 1, 'sites': 1}
        assert m['Borealis']['in_use'] == {'items': 0, 'models': 0, 'racks': 0, 'sites': 0}

    def test_no_counts_without_the_inventorys_permission(self, client, fleet):
        uc = _as(fleet['admin'], 'uc', ['dcim_catalog_view'])
        d, m = _by_name(uc, '/api/v1/dcim/brands?usage=1')
        assert d['usage'] is False and 'in_use' not in m['Acme']


# ── The panel: the views, in node ──────────────────────────────────────────────────────────

_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
let puede = true;
_dcimMay = (p) => p === 'dcim_catalog_manage' && puede;
// The address, for the view that travels in it.
let __url = '';
window.history = {replaceState: (s, tt, u) => { __url = String(u); }, pushState() {}};
window.location.href = 'http://x/admin?tab=models';
let pedido = '';
apiGet = async (u) => { pedido = u; return {brands: ROWS, usage: true}; };
renderDcim = () => {};

const ROWS = [
    {uid: 'b1', name: 'Acme', description: 'conmutadores', models: 3, url: 'https://acme.example',
     support_url: 'https://help.acme.example', account: 'C-1',
     trees: {'device-types': 2, 'component-types': 1}, platforms: 0,
     in_use: {items: 2, models: 1, racks: 1, sites: 1}},
    {uid: 'b2', name: 'Borealis', description: '', models: 1, url: '', support_url: '',
     account: '', trees: {'rack-types': 1}, platforms: 0,
     in_use: {items: 7, models: 2, racks: 3, sites: 2}},
    {uid: 'b3', name: 'cumulus', description: '', models: 0, url: 'https://c.example',
     support_url: '', account: 'X', trees: {}, platforms: 0,
     in_use: {items: 0, models: 0, racks: 0, sites: 0}},
    // Only platforms: no model at all.
    {uid: 'b4', name: 'Sistemas Norte', description: '', models: 0, url: '', support_url: '',
     account: '', trees: {}, platforms: 2, in_use: {items: 0, models: 0, racks: 0, sites: 0}},
];
const go = (uid) => `_dcBrandGo(${jsStr(uid)}`;
_dcCatTab = 'brands';
_dcBrands = {rows: ROWS, usage: true, asked: true};

// 1. The switcher, on the table view (the default).
_dcBrandView = 'table';
const t0 = _dcBrandsHtml();
__o.sw = {n: (t0.match(/_dcBrandGoView\(/g) || []).length,
          tableOn: /btn btn-primary"\s*onclick="_dcBrandGoView\(&quot;table&quot;\)"/.test(t0),
          hole: t0.includes('id="dcbrd-container"')};

// 2. The view goes to the address, and comes back from it; the default stays out of it.
_dcBrandGoView('trees');
__o.url = __url;
_dcBrandGoView('table');
__o.urlTable = __url;
_dcCatUrlRead = false;
window.location.search = '?ctab=brands&bview=usage';
_dcCatUrlLoad();
__o.loaded = _dcBrandView;
_dcBrandView = 'nonsense';
__o.unknown = _dcBrandViewNow();
const tu = _dcBrandsHtml();
__o.unknownIsTable = tu.includes('id="dcbrd-container"');

// 4. In use: only brands with items, most first; the counts; and the request.
_dcBrandView = 'usage';
const u1 = _dcBrandsHtml();
__o.usage = {order: [...u1.matchAll(/_dcBrandGo\(&quot;(b\d)&quot;/g)].map(m => m[1]),
             counts: u1.includes('>7</td>') && u1.includes('>3</td>')};
_dcBrands = {rows: ROWS, usage: false, asked: true};
__o.usageNoPerm = _dcBrandsHtml().includes(t('dcim_brand_use_noperm'));
_dcBrands = {rows: ROWS, usage: false, asked: false};
_dcBrandsBusy = false;
_dcBrandsHtml();
await Promise.resolve(); await Promise.resolve();
__o.usageAsked = pedido;
_dcBrands = {rows: ROWS, usage: true, asked: true};

// 5. By model type: one group per brand with models, a line per tree; folding; a click.
_dcBrandView = 'trees';
const r1 = _dcBrandsHtml();
__o.trees = {fold: r1.includes('_dcBrandFold(&quot;b1&quot;)'),
             noEmpty: !r1.includes('_dcBrandFold(&quot;b3&quot;)'),
             lines: (r1.match(/_dcBrandGoTree\(/g) || []).length,
             comp: r1.includes(_dcCatTreeName('component-types'))};
_dcBrandShut = new Set(['b1']);
const r2 = _dcBrandsHtml();
__o.folded = (r2.match(/_dcBrandGoTree\(/g) || []).length;
_dcBrandShut = new Set();
let abierto = 0;
_dcCatOpen = () => { abierto++; };
_dcCatKind = 'server';
_dcBrandGoTree('b1', 'Acme', 'component-types');
__o.treeGo = {tree: _dcCatTree, kind: _dcCatKind, brand: _dcCatBrand, tab: _dcCatTab,
              opened: abierto};
_dcCatTab = 'brands';
_dcCatTree = '';
// A brand with only platforms is listed, with a «Platforms» line that opens that tab narrowed
// to the brand by its uid.
__o.plats = {listed: r1.includes('_dcBrandFold(&quot;b4&quot;)'),
             line: r1.includes('_dcBrandGoPlats(&quot;b4&quot;,&quot;Sistemas Norte&quot;)'),
             noLineWithout: !r1.includes('_dcBrandGoPlats(&quot;b1&quot;')};
_dcPlatQ = 'algo';
_dcBrandGoPlats('b4', 'Sistemas Norte');
__o.platsGo = {tab: _dcCatTab, brand: _dcPlatBrand, q: _dcPlatQ};
_dcPlats = {rows: [{uid: 'p1', name: 'NorteOS 1', brand_uid: 'b4', brand: 'Sistemas Norte'},
                   {uid: 'p2', name: 'Norte Sistemas Viejo', brand_uid: '', brand: ''},
                   {uid: 'p3', name: 'AcmeOS', brand_uid: 'b1', brand: 'Acme'}],
           kinds: [], lifecycle: []};
const pl = _dcPlatsHtml();
__o.platsTab = {p1: pl.includes('_dcPlatInfo(&quot;p1&quot;)'),
                p2: pl.includes('_dcPlatInfo(&quot;p2&quot;)'),
                p3: pl.includes('_dcPlatInfo(&quot;p3&quot;)'),
                chip: pl.includes('Sistemas Norte<i class="bi bi-x-lg')};
_dcPlatSel = new Set();
_dcPlatSelAll(true);
__o.platsSelAll = [..._dcPlatSel].sort();
_dcPlatBrand = '';
_dcCatTab = 'brands';

// 7. The filter of these views, and its empty answer.
_dcBrandView = 'trees';
_dcBrandQ = 'BOREAL';
const f1 = _dcBrandViewBody();
__o.filter = {only: f1.includes('_dcBrandFold(&quot;b2&quot;)')
                    && !f1.includes('_dcBrandFold(&quot;b1&quot;)')};
_dcBrandQ = 'zzz';
__o.filterNone = _dcBrandViewBody().includes(t('dcim_brand_q_none'));
_dcBrandQ = '';

// 8. The table is not drawn while another view is showing.
let dibujada = 0;
const _real = renderDcBrd;
renderDcBrd = () => { dibujada++; };
_dcBrandView = 'trees';
_dcBrandsMount();
__o.mountOther = dibujada;
_dcBrandView = 'table';
_dcBrandsMount();
__o.mountTable = dibujada;
renderDcBrd = _real;
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
class TestTheSwitcher:

    def test_three_views_and_the_table_by_default(self, out):
        assert out['sw'] == {'n': 3, 'tableOn': True, 'hole': True}

    def test_the_view_travels_in_the_address(self, out):
        assert 'bview=trees' in out['url']
        assert 'bview' not in out['urlTable'], 'the default view should not clutter the URL'
        assert out['loaded'] == 'usage'

    def test_an_unknown_view_is_the_table(self, out):
        assert out['unknown'] == 'table' and out['unknownIsTable']

    def test_the_table_is_drawn_only_in_its_own_view(self, out):
        assert out['mountOther'] == 0 and out['mountTable'] == 1


@_needs_node
class TestInUseView:

    def test_only_brands_with_items_most_first(self, out):
        assert out['usage']['order'] == ['b2', 'b1']
        assert out['usage']['counts']

    def test_asks_the_server_for_usage(self, out):
        assert out['usageAsked'] == '/api/v1/dcim/brands?usage=1'

    def test_says_so_without_the_inventory_permission(self, out):
        assert out['usageNoPerm']


@_needs_node
class TestByModelType:

    def test_a_group_per_brand_with_models_and_a_line_per_tree(self, out):
        assert out['trees'] == {'fold': True, 'noEmpty': True, 'lines': 3, 'comp': True}

    def test_a_brand_with_only_platforms_is_listed_with_its_count(self, out):
        assert out['plats'] == {'listed': True, 'line': True, 'noLineWithout': True}

    def test_its_platforms_line_opens_that_tab_narrowed_by_uid(self, out):
        """By uid, not by a text search: «Norte Sistemas Viejo» has no brand and stays out."""
        assert out['platsGo'] == {'tab': 'platforms', 'brand': 'b4', 'q': ''}
        assert out['platsTab'] == {'p1': True, 'p2': False, 'p3': False, 'chip': True}

    def test_select_all_marks_only_what_the_brand_filter_shows(self, out):
        assert out['platsSelAll'] == ['p1']

    def test_folding_hides_its_lines(self, out):
        assert out['folded'] == 1

    def test_a_line_opens_the_models_of_that_brand_and_tree(self, out):
        assert out['treeGo'] == {'tree': 'component-types', 'kind': '', 'brand': 'b1',
                                 'tab': 'list', 'opened': 1}


@_needs_node
class TestTheFilter:

    def test_narrows_the_views(self, out):
        assert out['filter']['only'] and out['filterNone']
