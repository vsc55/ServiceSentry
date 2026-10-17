#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalogue › Library › Summary: «how is the library?», and every figure a door.

`GET /api/v1/dcim/catalog/summary` answers in one response what the view draws: models by
shape, brands (and how many are really in the installation), platforms out of support or losing
it within six months, connectors and their families, the data-quality counts, and the imports.

Each figure is counted with the SAME condition as the list filter it lands on, which is checked
here by asking the list: a figure that does not match its list is worse than none. What is
installed is the inventory's answer — only with `dcim_view`, over what the caller may see, and
`null` (unknown) rather than zero without it. The imports are a manager's.

The panel side, in node: the tiles, the three cards, the doors (each figure to its filtered
list), and the platforms' support filter they land on.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

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


def _day(delta):
    return (datetime.now(timezone.utc).date() + timedelta(days=delta)).isoformat()


@pytest.fixture()
def lib(client, admin):
    """An import, a hand-written model with no brand record, one item placed in each of two
    companies, a template, and four platforms: out of support, losing it soon, fine, undated."""
    _login(client)
    c = client
    cat = admin._dcim_catalog
    cat.replace('library', [
        {'manufacturer': 'Acme', 'model': 'SW-48', '_tree': 'device-types',
         'ports': {'interfaces': {'1000base-t': 48}}},
        {'manufacturer': 'Acme', 'model': 'Blank-1U', '_tree': 'device-types'},
        {'manufacturer': 'Borealis', 'model': 'R42', '_tree': 'rack-types'},
        {'manufacturer': 'Borealis', 'model': 'DIMM-16', '_tree': 'component-types',
         'kind': 'memory'},
    ])
    uid = {r['model']: r['uid'] for r in cat.list()}
    uid['Hand-1'] = _uid(c.post('/api/v1/dcim/catalog',
                                json={'manufacturer': 'Cumulus', 'model': 'Hand-1'}))
    cat.set_image(uid['SW-48'], 'front', 'sw48.png')
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
    plats = {}
    for nombre, fin in (('OldOS 1', _day(-40)), ('SoonOS 2', _day(30)), ('FineOS 3', _day(900)),
                        ('NoDateOS', '')):
        plats[nombre] = _uid(c.post('/api/v1/dcim/platforms',
                                    json={'name': nombre, 'extra': {'eol': fin} if fin else {}}))
    _uid(c.post('/api/v1/dcim/builds', json={'name': 'Std', 'type_uid': uid['Hand-1'],
                                              'platform_uid': plats['SoonOS 2']}))
    return {'uid': uid, 'a': a, 'admin': admin}


def _sum(c):
    r = c.get('/api/v1/dcim/catalog/summary')
    assert r.status_code == 200
    return r.get_json()


class TestTheFigures:

    def test_models_by_shape(self, client, lib):
        m = _sum(client)['models']
        assert m['total'] == 5
        assert {x['name']: x['count'] for x in m['trees']} == {
            'device-types': 3, 'rack-types': 1, 'component-types': 1}

    def test_each_quality_figure_is_the_count_of_its_list(self, client, lib):
        q = _sum(client)['quality']
        assert q == {'no_image': 4, 'no_ports': 2, 'no_brand': 1, 'manual': 1, 'unused': 2}
        for clave, filtro in (('no_image', 'img=none'), ('no_ports', 'ports=none'),
                              ('no_brand', 'brand_uid=none'), ('manual', 'source=manual'),
                              ('unused', 'unused=1')):
            d = client.get('/api/v1/dcim/catalog?' + filtro).get_json()
            assert d['total'] == q[clave], clave

    def test_brands_and_how_many_are_installed(self, client, lib):
        s = _sum(client)
        assert s['brands'] == {'total': 3, 'in_use': 1}
        assert [b['name'] for b in s['in_use_brands']] == ['Acme']
        assert s['in_use_brands'][0]['items'] == 2

    def test_connectors_and_their_families(self, client, lib):
        c = _sum(client)['connectors']
        assert c['total'] > 0 and 0 < c['families'] <= c['total']


class TestWhatIsInstalledIsTheInventorysAnswer:

    def test_counted_over_what_the_caller_may_see(self, lib):
        """Company A's reader: B's placed blank is not theirs — it counts as never placed."""
        ua = _as(lib['admin'], 'ua', ['dcim_view', 'dcim_catalog_view', f'org.{lib["a"]}.view'])
        s = _sum(ua)
        assert s['quality']['unused'] == 3
        assert s['brands']['in_use'] == 1 and s['in_use_brands'][0]['items'] == 1

    def test_unknown_without_the_inventorys_permission(self, lib):
        solo = _as(lib['admin'], 'solo', ['dcim_catalog_view'])
        s = _sum(solo)
        assert s['usage'] is False
        assert s['quality']['unused'] is None and s['brands']['in_use'] is None
        assert s['in_use_brands'] is None


class TestSupportRunningOut:

    def test_out_of_support_and_soon_by_the_end_of_support_date(self, client, lib):
        p = _sum(client)['platforms']
        assert (p['total'], p['gone'], p['soon']) == (4, 1, 1)
        assert [(x['name'], x['state']) for x in p['expiring']] == [('SoonOS 2', 'soon'),
                                                                   ('OldOS 1', 'gone')]
        assert p['expiring'][0]['builds'] == 1

    def test_the_six_months_are_said(self, client, lib):
        s = _sum(client)
        assert s['today'] == _day(0) and s['soon_until'] == _day(182)


class TestTheImports:

    def test_a_managers_and_each_lands_on_its_models(self, client, lib):
        imps = _sum(client)['imports']
        assert [(i['source'], i['count']) for i in imps] == [('library', 4)]
        d = client.get('/api/v1/dcim/catalog?import=' + imps[0]['key']).get_json()
        assert d['total'] == 4

    def test_not_a_readers(self, lib):
        lector = _as(lib['admin'], 'lector', ['dcim_view', 'dcim_catalog_view'])
        assert _sum(lector)['imports'] is None


# ── The panel, in node ─────────────────────────────────────────────────────────────────────

_PROBE = r"""
const __o = {};
globalThis.__out = __o;
__wait = (async () => {
const may = new Set(['dcim_catalog_manage']);
_dcimMay = (p) => may.has(p);
_sbHighlightSub = () => {};
renderDcim = () => {};
let fui = [];
_dcLibGo = (s) => { fui.push(s); };
const S = {
    models: {total: 10, trees: [{name: 'device-types', count: 7}, {name: 'rack-types', count: 3}]},
    brands: {total: 4, in_use: 2},
    platforms: {total: 6, gone: 1, soon: 2, expiring: [
        {uid: 'p2', name: 'SoonOS', eol: '2099-01-01', state: 'soon', builds: 3, brand: ''},
        {uid: 'p1', name: 'OldOS', eol: '2000-01-01', state: 'gone', builds: 0, brand: ''}]},
    connectors: {total: 30, families: 5},
    quality: {no_image: 6, no_ports: 1, no_brand: 0, manual: 2, unused: 4},
    imports: [{source: 'library', at: '2026-10-01T10:00:00Z', count: 8,
               key: 'library@2026-10-01T10:00:00Z'}],
    in_use_brands: [{uid: 'b1', name: 'Acme', support_url: '', items: 9}],
    usage: true, today: '2026-10-16', soon_until: '2027-04-16'};
_dcLibSum = S;

// 1. The tiles, the quality, the support running out and the imports, for a manager.
const h = _dcLibSummaryHtml();
__o.mgr = {
    totals: ['>10<', '>4<', '>6<', '>30<'].every(x => h.includes(x)),
    segments: (h.match(/class="(ss-series-1|ss-series-3)" style="width:/g) || []).length,
    softEos: /<button[^>]*bg-danger-subtle text-danger-emphasis[^>]*_dcLibLandPlat\('gone'\)/.test(h)
             && /<button[^>]*bg-warning-subtle text-warning-emphasis[^>]*_dcLibLandPlat\('soon'\)/.test(h)
             && !/btn-(danger|warning)/.test(h),
    headed: (h.match(/class="ss-card-header /g) || []).length,
    surfaced: (h.match(/class="card [^"]*ss-surface/g) || []).length,
    dashed: (h.match(/list-group-flush ss-list-dashed/g) || []).length,
    legend: h.includes('_dcLibLand(&#39;tree&#39;') || h.includes("_dcLibLand('tree',&quot;rack-types&quot;)"),
    inUse: h.includes(esc(tf('dcim_lib_brands_in_use', 2))) && h.includes('_dcLibLandBrands()'),
    gone: h.includes("_dcLibLandPlat('gone')") && h.includes(esc(tf('dcim_lib_eos_gone_n', 1))),
    soon: h.includes("_dcLibLandPlat('soon')") && h.includes(esc(tf('dcim_lib_eos_soon_n', 2))),
    conns: h.includes("_dcLibGo('connectors')"),
    quality: ['img', 'ports', 'brand', 'unused', 'manual'].map(
        k => h.includes(`_dcLibLand(&quot;${k}&quot;)`)),
    expiring: h.includes('_dcLibLandPlat(&quot;soon&quot;)') && h.includes('SoonOS')
              && h.includes(esc(tf('dcim_lib_in_builds', 3))),
    imports: h.includes("_dcLibLand('import',&quot;library@2026-10-01T10:00:00Z&quot;)"),
    importBtn: h.includes('_dcLibImportOpen()'),
    newModel: _dcLibHeadHtml('summary').includes('_dcCatEdit(null)')
              && !_dcLibHeadHtml('list').includes('_dcCatEdit(null)') && !h.includes('_dcCatEdit(null)'),
    readersCard: h.includes('_dcLibBrandDrawer(')};
// Unknown is not zero: without the inventory, the row is not drawn.
_dcLibSum = Object.assign({}, S, {quality: Object.assign({}, S.quality, {unused: null})});
__o.noUnused = !_dcLibSummaryHtml().includes('_dcLibLand(&quot;unused&quot;)');
// A reader: no imports, the brands in use instead — or why not.
may.delete('dcim_catalog_manage');
_dcLibSum = S;
const r = _dcLibSummaryHtml();
__o.reader = {imports: r.includes("_dcLibLand('import'"), importBtn: r.includes('_dcLibImportOpen()'),
              newModel: _dcLibHeadHtml('summary').includes('_dcCatEdit(null)'),
              inUse: r.includes('_dcLibBrandDrawer(&quot;b1&quot;)')
                     && r.includes(esc(tf('dcim_lib_n_placed', 9)))};
_dcLibSum = Object.assign({}, S, {in_use_brands: null});
__o.readerNoPerm = _dcLibSummaryHtml().includes(esc(t('dcim_brand_use_noperm')));
may.add('dcim_catalog_manage');
// Not loaded yet: it is asked for, once.
let pedidos = 0;
apiGet = async (u) => { pedidos++; __o.asked = u; return S; };
_dcLibSum = null;
_dcLibSumBusy = false;
_dcLibSummaryHtml();
_dcLibSummaryHtml();
await Promise.resolve(); await Promise.resolve();
__o.loads = pedidos;
// Entering the Summary asks for it again; another view leaves it as it is.
_dcLibBooted = true;
_dcLibLastUrl = '';
_dcCat = {rows: [], counts: {}};
_dcLibSum = S;
window._ssNavPicked = {pageId: 'models', slug: 'brands'};
window.location.pathname = '/catalog/library/brands';
renderDcLibrary();
__o.keptOnBrands = _dcLibSum === S;
window._ssNavPicked = {pageId: 'models', slug: 'summary'};
window.location.pathname = '/catalog/library/summary';
renderDcLibrary();
__o.askedOnEntry = _dcLibSum === null;
_dcLibSum = S;

// 2. The doors: each to its list with ITS filter and nothing else.
const land = (que, val) => {
    _dcCatFiltersReset();
    _dcCatQ = 'stale';
    _dcCatView = 'makers';
    fui = [];
    _dcLibLand(que, val);
    return {img: _dcCatImg, ports: _dcCatNoPorts, brand: _dcCatBrand, unused: _dcCatUnused,
            src: _dcCatSrc, imp: _dcCatImp, tree: _dcCatTree, q: _dcCatQ, view: _dcCatView,
            went: fui.join()};
};
__o.land = {img: land('img'), ports: land('ports'), brand: land('brand'), unused: land('unused'),
            manual: land('manual'), imp: land('import', 'library@x'), tree: land('tree', 'rack-types')};
_dcBrandView = 'table';
let limpio = 0;
window._ltFilterClear_dcbrd = () => { limpio++; };
fui = [];
_dcLibLandBrands();
__o.landBrands = {view: _dcBrandView, q: limpio === 1 ? '' : 'kept', went: fui.join()};
_dcPlatBrand = 'b9';
fui = [];
_dcLibLandPlat('gone');
__o.landPlat = {eos: _dcPlatEos, brand: _dcPlatBrand, went: fui.join()};
_dcLibLandPlat('nonsense');
__o.landPlatBad = _dcPlatEos;

// 3. Where the support figures land: the platforms, by their end of support.
const hoy = new Date();
const iso = (d) => new Date(hoy.getTime() + d * 86400000).toISOString().slice(0, 10);
const [h0, p0] = _dcPlatEosDays();
__o.states = [iso(-1), iso(30), iso(400), ''].map(d => _dcPlatEosOf({extra: {eol: d}}, h0, p0));
_dcPlats = {rows: [
    {uid: 'p1', name: 'OldOS', brand_uid: '', extra: {eol: iso(-1)}, builds: 0},
    {uid: 'p2', name: 'SoonOS', brand_uid: '', extra: {eol: iso(30)}, builds: 0},
    {uid: 'p3', name: 'FineOS', brand_uid: '', extra: {eol: iso(400)}, builds: 0}],
    kinds: [], lifecycle: []};
_dcPlatBrand = '';
_dcPlatQ = '';
_dcPlatEos = 'gone';
const pg = _dcPlatsHtml();
__o.platsGone = {p1: pg.includes('_dcPlatInfo(&quot;p1&quot;)'),
                 p2: pg.includes('_dcPlatInfo(&quot;p2&quot;)'),
                 seg: (pg.match(/_dcPlatEosSet\(/g) || []).length};
_dcPlatEos = '';
const pa = _dcPlatsHtml();
__o.platsAll = ['p1', 'p2', 'p3'].every(u => pa.includes(`_dcPlatInfo(&quot;${u}&quot;)`));
// The table colours the end of support as the Summary counts it: red gone, amber soon.
__o.platsColours = {gone: pa.includes(`bg-danger-subtle text-danger-emphasis">${iso(-1)}<`),
                    soon: pa.includes(`bg-warning-subtle text-warning-emphasis">${iso(30)}<`),
                    fine: !pa.includes(`">${iso(400)}</span>`)};
// …and the choice goes to the address.
window.history = {replaceState: (s, tt, u) => { __o.platUrl = String(u); }, pushState() {}};
window.location.pathname = '/catalog/library/platforms';
_dcCatTab = 'platforms';
_dcPlatEosSet('soon');
__o.platEos = _dcPlatEos;
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
class TestTheView:

    def test_a_managers_summary(self, out):
        m = out['mgr']
        assert m['totals'] and m['segments'] == 2 and m['inUse'] and m['gone'] and m['soon']
        assert m['conns'] and m['quality'] == [True] * 5 and m['expiring']
        assert m['imports'] and m['importBtn'] and m['newModel']
        assert m['readersCard'] is False

    def test_it_wears_the_designs_colours(self, out):
        """The approved design: soft state badges beside the big figures, not solid red and
        yellow buttons, and each card under the panel's tinted header band."""
        m = out['mgr']
        assert m['softEos'] and m['headed'] == 3
        # The four tiles and the three cards on the panel's card surface, not the page's colour,
        # and the cards' rows as lines of the card rather than boxes of their own.
        assert m['surfaced'] == 7 and m['dashed'] == 3

    def test_unknown_is_not_drawn_as_a_figure(self, out):
        assert out['noUnused']

    def test_a_readers_summary(self, out):
        assert out['reader'] == {'imports': False, 'importBtn': False, 'newModel': False,
                                 'inUse': True}
        assert out['readerNoPerm']

    def test_asked_once_while_it_is_on_its_way(self, out):
        assert out['loads'] == 1 and out['asked'] == '/api/v1/dcim/catalog/summary'

    def test_asked_again_on_every_entry_and_only_then(self, out):
        """It counts what the other views change: one read a quarter of an hour ago says what
        was true then. Another view does not throw it away."""
        assert out['askedOnEntry'] is True and out['keptOnBrands'] is True


@_needs_node
class TestTheDoors:

    def test_each_figure_lands_on_the_models_with_only_its_filter(self, out):
        base = {'img': '', 'ports': '', 'brand': '', 'unused': '', 'src': '', 'imp': '',
                'tree': '', 'q': '', 'view': 'list', 'went': 'models'}
        esperado = {'img': {'img': 'none'}, 'ports': {'ports': 'none'},
                    'brand': {'brand': 'none'}, 'unused': {'unused': '1'},
                    'manual': {'src': 'manual'}, 'imp': {'imp': 'library@x'},
                    'tree': {'tree': 'rack-types'}}
        for k, delta in esperado.items():
            assert out['land'][k] == dict(base, **delta), k

    def test_the_brands_in_use_and_the_platforms(self, out):
        assert out['landBrands'] == {'view': 'usage', 'q': '', 'went': 'brands'}
        assert out['landPlat'] == {'eos': 'gone', 'brand': '', 'went': 'platforms'}
        assert out['landPlatBad'] == ''


@_needs_node
class TestThePlatformsSupportFilter:

    def test_the_state_of_each_by_its_end_of_support(self, out):
        assert out['states'] == ['gone', 'soon', 'ok', 'none']

    def test_the_list_shows_only_that_support(self, out):
        assert out['platsGone'] == {'p1': True, 'p2': False, 'seg': 4}
        assert out['platsAll']

    def test_the_table_colours_the_end_of_support_as_the_summary_counts_it(self, out):
        assert out['platsColours'] == {'gone': True, 'soon': True, 'fine': True}

    def test_the_choice_goes_to_the_address(self, out):
        assert out['platEos'] == 'soon'
        assert out['platUrl'] == '/catalog/library/platforms?eos=soon'
