#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The «Borrar Una Serie» dialog, in `node` on the panel's real script.

Reported from the screen, twice over:

- pressing the button took a while to show anything, so it seemed to do nothing — the dialog
  waited for the whole history index before opening;
- once open, changing the module did not change the items, and the series list stayed empty
  — the module picker still refreshed only the series.

And what was asked: an item of twenty or thirty series is forgotten in one go, through
«Todas las series del elemento».
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('node') is None,
                                reason='no node: nothing to run the script with')

_PROBE = r"""
__out = {};
// Three selects and a button, as plain objects: enough of a DOM for the picker.
const sel = () => {
    const o = {value: '', disabled: false, _html: ''};
    Object.defineProperty(o, 'innerHTML', {
        get() { return o._html; },
        set(v) {
            o._html = v;
            const vals = [...String(v).matchAll(/<option value="([^"]*)"/g)].map(m => m[1]);
            o.options = vals.map(x => ({value: x}));
            const sel = /<option value="([^"]*)"[^>]*selected/.exec(v);
            o.value = sel ? sel[1] : (vals.length ? vals[0] : '');
        }});
    o.innerHTML = '';
    return o;
};
const dom = {hcsModule: sel(), hcsItem: sel(), hcsSeries: sel(), hcsDelete: {disabled: true},
             historyClearModal: {}};
document.getElementById = (id) => dom[id] || null;
let shown = 0, hidden = 0;
bootstrap = {Modal: {getOrCreateInstance: () => ({show() { shown++; }, hide() { hidden++; }})}};
let resolveIndex, apiGetCalls = 0;
apiGet = () => { apiGetCalls++; return new Promise(ok => { resolveIndex = ok; }); };
_historyIsLive = () => false;
const deletes = [];
apiDelete = (url) => { deletes.push(url); return Promise.resolve({data: {ok: true, series: 3}}); };
showToast = () => {};

const index = [
    {module: 'snmp', pretty_name: 'SNMP', key: 'host.a/eth0', item: 'host.a', item_label: 'Switch A', label: 'Switch A / eth0'},
    {module: 'snmp', pretty_name: 'SNMP', key: 'host.a/eth1', item: 'host.a', item_label: 'Switch A', label: 'Switch A / eth1'},
    {module: 'snmp', pretty_name: 'SNMP', key: 'host.a/disk', item: 'host.a', item_label: 'Switch A', label: 'Switch A / disk'},
    {module: 'snmp', pretty_name: 'SNMP', key: 'host.b/eth0', item: 'host.b', item_label: 'Switch B', label: 'Switch B / eth0'},
    {module: 'ping', pretty_name: 'Ping', key: 'r1', item: 'r1', item_label: 'Router', label: 'Router'},
];

// ── It opens at once, saying it is loading ──────────────────────────────────────
showHistoryClearSeriesModal();
__out.openBeforeIndex = shown === 1;
__out.loading = dom.hcsModule.disabled && dom.hcsModule.innerHTML.includes(t('loading'));
__out.buttonOffWhileLoading = dom.hcsDelete.disabled;

// The index arrives: what the awaiting half of the opener does, done here by hand — the
// harness reads the result synchronously, before any promise settles.
_historyClearIndex = index;
for (const id of ['hcsModule', 'hcsItem', 'hcsSeries']) dom[id].disabled = false;
_historyClearFillModules();
{
    __out.filled = !dom.hcsModule.disabled && dom.hcsModule.options.length === 2;
    // Modules sorted by name: Ping first.
    __out.firstModule = dom.hcsModule.value;
    __out.pingItems = dom.hcsItem.options.map(o => o.value);
    __out.pingSeries = dom.hcsSeries.options.map(o => o.value);

    // ── Changing the module changes the items AND the series ─────────────────────
    dom.hcsModule.value = 'snmp';
    _historyClearFillItems();
    __out.snmpItems = dom.hcsItem.options.map(o => o.value);
    __out.snmpItemLabel = dom.hcsItem.innerHTML.includes('Switch A (3)');
    __out.snmpSeries = dom.hcsSeries.options.map(o => o.value);
    __out.allFirst = dom.hcsSeries.options[0].value === '' && dom.hcsSeries.innerHTML.includes(tf('history_clear_item_all', 3));
    __out.buttonOn = !dom.hcsDelete.disabled;

    // ── «Every series of the item» deletes the item ──────────────────────────────
    _historyClearSeriesConfirmed();
    __out.deleteUrl = deletes[0];
    // The delete settles on a microtask; what follows it is checked on the next one, after the
    // probe — so the closing is pinned by reading the handler instead (see the test).
    __out.handler = String(_historyClearSeriesConfirmed);
}
"""


@pytest.fixture(scope='module')
def panel():
    """The served panel, logged in: its HTML and its script."""
    pytest.importorskip('flask')
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
    return {'html': c.get('/admin').get_data(as_text=True), 'js': panel_bundle(c)}


@pytest.fixture(scope='module')
def out(panel):
    """One `node` run for the whole module: starting it costs more than looking."""
    return node_run(panel['js'], _PROBE)


class TestItOpensAtOnce:
    def test_before_the_index_arrives(self, out):
        assert out['openBeforeIndex']

    def test_saying_it_is_loading_with_nothing_to_press(self, out):
        assert out['loading'] and out['buttonOffWhileLoading']


class TestTheModuleDrivesTheItemsAndTheSeries:
    def test_filled_when_the_index_arrives(self, out):
        assert out['filled']
        assert out['firstModule'] == 'ping'
        assert out['pingItems'] == ['r1'] and out['pingSeries'] == ['r1']

    def test_changing_the_module_changes_the_items(self, out):
        assert out['snmpItems'] == ['host.a', 'host.b']
        assert out['snmpItemLabel'], 'each item with its label and how many series'

    def test_and_the_series_of_the_item(self, out):
        assert out['snmpSeries'] == ['', 'host.a/eth0', 'host.a/eth1', 'host.a/disk']


class TestEverySeriesOfTheItem:
    def test_offered_first(self, out):
        assert out['allFirst'] and out['buttonOn']

    def test_deletes_the_item(self, out):
        assert out['deleteUrl'] == '/api/v1/history/item?module=snmp&item=host.a'


class TestTheServedDialog:
    def test_the_module_picker_refreshes_the_items(self, panel):
        """It refreshed only the series, so changing module left the items of the previous one
        and an empty series list."""
        import re                                                    # noqa: PLC0415
        m = re.search(r'<select[^>]*id="hcsModule"[^>]*>', panel['html'], re.S)
        assert m and 'onchange="_historyClearFillItems()"' in m.group(0)
        assert 'id="hcsItem"' in panel['html']

    def test_and_closes_at_once_without_re_reading_the_index(self, out):
        """Reported: the toast said it was deleted while the dialog stayed up for seconds,
        re-reading the whole history index to refill itself."""
        h = out['handler']
        tras = h.split('apiDelete(url)')[1]
        assert '.hide()' in tras
        assert '/api/v1/history/index' not in tras
