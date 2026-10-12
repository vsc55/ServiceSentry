#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The panel defects of the 2026-10-12 audit's sixth batch, pinned against the served script.

Two kinds of guard live here, both on what the server actually sends:

* **Static, over the whole page.** Every `<script>` of `/admin`, `/status` and `/login` is parsed
  with acorn and scoped with eslint-scope, and two things are refused: a name read but declared
  nowhere (the overview's syslog table read `device` after a host → device rename and spun
  forever), and `localStorage`/`sessionStorage` touched while the script LOADS without a `try`
  around it (blocked storage throws, and one throw at the top level leaves every later section
  undefined). Both libraries are looked for locally — `SS_JS_NODE_MODULES`, node's own
  resolution, then the `node_modules` VS Code extensions ship — and the guard SKIPS without them:
  it is a net, not a dependency of the suite.
* **Behavioural, in `node`** (the harness of `tests/helpers.py`): a Save clicked twice creates
  one device / webhook / Teams channel; a late answer from the device or cluster logs does not
  paint over a newer one; leaving Status while it loads leaves no poll behind; the interval save
  sees a 400; links to History and Syslog switch panes instead of reloading; resize listeners do
  not stack; toasts are not escaped twice; no outline buttons anywhere.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import shutil
import subprocess

import pytest

from tests.conftest import _login                                   # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')


# ── static: undeclared names and load-time storage ──────────────────────────
_SCOPE_JS = r"""
const path = require('path'), fs = require('fs');
const NM = process.argv[2];
const acorn = require(path.join(NM, 'acorn'));
const scope = require(path.join(NM, 'eslint-scope'));
const src = fs.readFileSync(process.argv[3], 'utf8');
const out = {parse: '', undeclared: {}, storage: []};
let ast;
try {
  ast = acorn.parse(src, {ecmaVersion: 2022, sourceType: 'script', locations: true, ranges: true,
                          allowAwaitOutsideFunction: true});
} catch (e) { out.parse = String(e.message); console.log(JSON.stringify(out)); process.exit(0); }
const g = scope.analyze(ast, {ecmaVersion: 2022, sourceType: 'script'}).globalScope;
const declared = new Set(g.variables.map(v => v.name));
const assigned = new Set(), typeofd = new Set(), named = new Set();
const parent = new Map();
const kids = (n, f) => { for (const k of Object.keys(n)) {
  if (k === 'loc' || k === 'range') continue;
  const v = n[k];
  if (Array.isArray(v)) v.forEach(c => c && typeof c.type === 'string' && f(c, n));
  else if (v && typeof v.type === 'string') f(v, n);
} };
(function walk(n, p) {
  parent.set(n, p);
  // `typeof X` says the author knows X may be missing (a lazily loaded library).
  if (n.type === 'UnaryExpression' && n.operator === 'typeof' && n.argument.type === 'Identifier')
    typeofd.add(n.argument.name);
  // A camelCase name handed over as a STRING is defined by a factory (`window[name] = ...`):
  // the list tables publish their render/paging functions that way. All-lowercase words
  // ('device') are data, not function names, and are not excused.
  if (n.type === 'Literal' && typeof n.value === 'string' && /^[A-Za-z_$][\w$]*$/.test(n.value)
      && /[A-Z_]/.test(n.value) && p && (p.type === 'Property' || p.type === 'ArrayExpression'))
    named.add(n.value);
  kids(n, walk);
})(ast, null);
for (const r of g.through) if (r.isWrite()) assigned.add(r.identifier.name);
const known = new Set(Object.getOwnPropertyNames(globalThis).concat(process.argv[4].split(',')));
for (const r of g.through) {
  const n = r.identifier.name;
  if (declared.has(n) || assigned.has(n) || typeofd.has(n) || named.has(n) || known.has(n)) continue;
  (out.undeclared[n] = out.undeclared[n] || []).push(r.identifier.loc.start.line);
}
const FN = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression']);
(function walk2(n) {
  if (FN.has(n.type)) return;                       // runs later, not while loading
  if (n.type === 'Identifier' && (n.name === 'localStorage' || n.name === 'sessionStorage')) {
    const pp = parent.get(n);
    const isKey = pp && pp.type === 'MemberExpression' && pp.property === n && !pp.computed;
    let c = n, p = pp, safe = false;
    while (p) { if (p.type === 'TryStatement' && p.block === c) { safe = true; break; }
                c = p; p = parent.get(p); }
    if (!safe && !isKey) out.storage.push(n.loc.start.line);
  }
  kids(n, walk2);
})(ast);
console.log(JSON.stringify(out));
"""

#: What the browser (and the panel's `<script src>` tags) put on `window`.
_BROWSER = (
    'window document navigator location localStorage sessionStorage fetch Headers Request '
    'Response URL URLSearchParams FormData Blob File FileReader Image Event CustomEvent '
    'KeyboardEvent MouseEvent HTMLElement Element Node NodeFilter DOMParser MutationObserver '
    'ResizeObserver IntersectionObserver requestAnimationFrame cancelAnimationFrame '
    'getComputedStyle CSS history screen performance alert confirm prompt console setTimeout '
    'clearTimeout setInterval clearInterval queueMicrotask matchMedia AbortController TextEncoder '
    'TextDecoder crypto atob btoa structuredClone innerWidth innerHeight devicePixelRatio scrollTo '
    'scrollBy open close print XMLSerializer Path2D HTMLCanvasElement HTMLInputElement '
    'HTMLSelectElement HTMLTextAreaElement SVGElement PointerEvent DragEvent ClipboardItem '
    'Notification OffscreenCanvas createImageBitmap ImageData DOMRect DOMMatrix DOMMatrixReadOnly '
    'visualViewport getSelection Range indexedDB caches self top parent frames opener name event '
    'Worker BroadcastChannel WebSocket EventSource WebGLRenderingContext WebGL2RenderingContext '
    'AudioContext Audio HTMLImageElement HTMLVideoElement CanvasRenderingContext2D scrollX scrollY '
    'pageXOffset pageYOffset outerWidth outerHeight isSecureContext origin customElements '
    'bootstrap').split()


def _node_modules() -> str:
    """A `node_modules` holding both acorn (>= 8) and eslint-scope, or ''."""
    cands = []
    if os.environ.get('SS_JS_NODE_MODULES'):
        cands.append(os.environ['SS_JS_NODE_MODULES'])
    try:
        r = subprocess.run(['node', '-e', "console.log(require('path').dirname(require('path')"
                                          ".dirname(require.resolve('acorn'))))"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            cands.append(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return ''
    home = os.path.expanduser('~')
    for pat in ('.vscode/extensions/*/node_modules', '.vscode/extensions/*/server/node_modules',
                '.vscode/extensions/*/dist/node_modules'):
        cands.extend(sorted(glob.glob(os.path.join(home, pat))))
    for nm in cands:
        pkg = os.path.join(nm, 'acorn', 'package.json')
        if not (os.path.isfile(pkg) and os.path.isfile(os.path.join(nm, 'eslint-scope',
                                                                     'package.json'))):
            continue
        try:
            ver = json.load(io.open(pkg, encoding='utf-8')).get('version', '0')
        except (OSError, ValueError):
            continue
        if int(ver.split('.')[0]) >= 8:
            return nm
    return ''


def _page_js(client, url: str) -> str:
    html = client.get(url).get_data(as_text=True)
    trozos = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)
    assert trozos, f'{url} served no inline script'
    return '\n;\n'.join(trozos)


def _scope(js: str, tmp_path, nm: str) -> dict:
    sj = tmp_path / 't6ui_scope.js'
    sj.write_text(_SCOPE_JS, encoding='utf-8')
    pj = tmp_path / 't6ui_page.js'
    pj.write_text(js, encoding='utf-8')
    r = subprocess.run(['node', str(sj), nm, str(pj), ','.join(_BROWSER)],
                       capture_output=True, text=True, encoding='utf-8', timeout=300)
    assert r.returncode == 0, (r.stderr or '')[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture(scope='module')
def wa(tmp_path_factory):
    if shutil.which('node') is None:
        pytest.skip('no node: nothing to run the script with')
    from lib.web_admin import WebAdmin                              # noqa: PLC0415
    cfg = tmp_path_factory.mktemp('t6ui_cfg')
    var = tmp_path_factory.mktemp('t6ui_var')
    (cfg / 'config.json').write_text('{}', encoding='utf-8')
    w = WebAdmin(str(cfg), 'admin', 'secret', str(var),
                 pw_require_upper=False, pw_require_digit=False)
    w._csrf_enabled = False
    w.app.config['TESTING'] = True
    return w


@pytest.fixture(scope='module')
def client(wa):
    c = wa.app.test_client()
    _login(c)
    return c


@pytest.fixture(scope='module')
def nm():
    found = _node_modules()
    if not found:
        pytest.skip('acorn + eslint-scope not found locally (set SS_JS_NODE_MODULES)')
    return found


@pytest.mark.parametrize('url,logged', [('/admin', True), ('/status', True),
                                        ('/status', False), ('/login', False)])
class TestPageScripts:

    def _js(self, wa, client, url, logged):
        return _page_js(client if logged else wa.app.test_client(), url)

    def test_every_name_read_is_declared(self, wa, client, nm, tmp_path, url, logged):
        out = _scope(self._js(wa, client, url, logged), tmp_path, nm)
        assert not out['parse'], out['parse']
        assert out['undeclared'] == {}, f'{url}: names read but never declared: {out["undeclared"]}'

    def test_no_storage_touched_unguarded_while_loading(self, wa, client, nm, tmp_path, url,
                                                        logged):
        out = _scope(self._js(wa, client, url, logged), tmp_path, nm)
        assert out['storage'] == [], (f'{url}: localStorage read at load time without try '
                                      f'(script lines {out["storage"]})')


# ── behavioural, in node ─────────────────────────────────────────────────────
_PROBE = r"""
__out = {};
currentUser = {permissions: []};
const avisos = [];
showToast = (m, k) => { avisos.push([String(m), k]); };
const tarde = () => { let r; const p = new Promise(ok => { r = ok; }); return [p, r]; };
bootstrap.Modal.getInstance = () => ({hide() {}});

__wait = (async () => {
    // UI-1: the overview's syslog table names the host it read.
    __out.syslogHost = _DW_CELLS.syslog_host({hostname: 'sw-core-01'});

    // UI-3: Save clicked twice while the create is in flight creates ONE device.
    _deviceDraft = {name: 'srv-a', profiles: {}, kind: 'local'};
    _editingDeviceUid = null;
    _applyDeviceChecks = () => false;
    reloadDevices = async () => {};
    _snapshotDevice = () => {};
    const [pd, rd] = tarde();
    let posts = 0, puts = 0;
    apiPost = () => { posts++; return pd; };
    apiPut = async () => { puts++; return {ok: true}; };
    const s1 = saveDeviceModal(false), s2 = saveDeviceModal(false);
    rd({status: 200, data: {ok: true, uid: 'u1'}});
    await s1; await s2;
    await saveDeviceModal(false);          // released: the next Save goes through (an update)
    __out.device = [posts, puts];

    // UI-3: the same for a webhook and a Teams channel.
    configData = {};
    renderConfig = () => {};
    _cfgAdoptSection = () => {};
    _webhookValidateModal = () => true;  _webhookFormData = () => ({name: 'w'});
    _mstValidate = () => true;           _mstFormData = () => ({name: 'c'});
    _webhookEditId = null; _msteamsEditId = null;
    const [pw, rw] = tarde();
    let wposts = 0;
    apiPost = () => { wposts++; return pw; };
    const w1 = saveWebhook(), w2 = saveWebhook();
    const m1 = saveMsTeamsChannel(), m2 = saveMsTeamsChannel();
    rw({status: 200, data: {ok: true, webhook: {id: 'a'}, channel: {id: 'b'}}});
    await Promise.all([w1, w2, m1, m2]);
    __out.notify = wposts;

    // UI-4: the device logs paint the NEWEST request, not the last one to answer.
    _deviceLogsState = {addr: '10.0.0.1', src: 'internal', page: 1, pageSize: 50,
                        severity_max: '', q: '', since: '', until: '', sort: 'ts', order: 'desc'};
    const tbody = {children: [1], innerHTML: ''};
    document.getElementById = (id) => (id === 'hml-rows' ? tbody : null);
    _deviceLogsDrawTable = () => {};
    const resp = [];
    apiGet = () => { const [p, r] = tarde(); resp.push(r); return p; };
    const f1 = _deviceLogsFetch();
    _deviceLogsState.q = 'new';
    const f2 = _deviceLogsFetch();
    resp[1]({messages: [{message: 'new'}], total: 1});
    await f2;
    resp[0]({messages: [{message: 'old'}], total: 1});
    await f1;
    __out.devlogs = _deviceLogsState.rows.map(m => m.message);

    // UI-4: the cluster logs too.
    _clLogsState = {members: [], addrs: ['a'], sel: '', page: 1, pageSize: 50, severity_max: '',
                    q: '', since: '', until: '', auto: 0};
    const ctb = {children: [], innerHTML: ''};
    document.getElementById = (id) => (id === 'clLogsRows' ? ctb : null);
    const cresp = [];
    apiGet = () => { const [p, r] = tarde(); cresp.push(r); return p; };
    const c1 = _clLogsFetch(), c2 = _clLogsFetch();
    cresp[1]({messages: [{message: 'new', severity: 6}], total: 1});
    await c2;
    const despues = ctb.innerHTML;
    cresp[0]({messages: [{message: 'old', severity: 6}], total: 1});
    await c1;
    __out.cllogs = [despues.includes('new'), ctb.innerHTML.includes('old')];
    document.getElementById = () => null;

    // UI-5: leaving Status while it is still loading leaves no poll behind.
    let intervals = 0;
    setInterval = () => { intervals++; return 7; };
    clearInterval = () => {};
    _daemonRefresh = () => {};
    const [ps, rs] = tarde();
    apiGet = () => ps;
    const gen = _daemonPollGen;          // the shown handler takes it before rendering
    const start = _daemonStartPoll(gen);
    _daemonStopPoll();                   // the reader left
    rs({});
    await start;
    const stale = _daemonStartPoll(gen); // a start that was waiting on renderStatus
    await stale;
    __out.poll = [intervals, _daemonPollTimer];
    apiGet = async () => ({});
    await _daemonStartPoll();            // a real start still starts
    __out.pollStarts = intervals;
    _daemonStopPoll();

    // UI-6: the interval save sees a refusal (apiPut answers with the body).
    avisos.length = 0;
    apiPut = async () => ({error: 'nope'});
    __out.interval = [await _daemonPersistInterval(30), avisos.map(a => a[1])];

    // UI-7: History and Syslog switch panes when this page has them.
    SS_STANDALONE_PAGES = [{id: 'history', url: '/history'}, {id: 'syslog', url: '/syslog'}];
    const panes = [];
    _navTab = (t) => { panes.push(t); };
    document.querySelector = (sel) => (/#tab-(history|syslog)/.test(sel) ? {} : null);
    location.href = '';
    _goToHistory('ping', 'h1');
    _DW_NAV['t6ui_w'] = {url: '/syslog'};
    _dwModuleDef = () => null;
    _dwBaseId = (w) => w;
    _dwNavigate('t6ui_w');
    __out.nav = [panes, location.href];
    document.querySelector = () => null;
    _navUrl('/history?module=a&key=b');
    __out.navAway = location.href;

    // Minor: one resize listener per element, however often it is fitted.
    const listeners = new Set();
    addEventListener = (ev, fn) => { if (ev === 'resize') listeners.add(fn); };
    removeEventListener = (ev, fn) => { if (ev === 'resize') listeners.delete(fn); };
    const el = {isConnected: true, style: {}, getBoundingClientRect: () => ({top: 0}),
                closest: () => ({clientHeight: 500})};
    for (let i = 0; i < 3; i++) { fitToViewportBottom(el); capToScrollBox(el); }
    __out.resize = listeners.size;
})();
"""


@pytest.fixture(scope='module')
def out(client):
    return node_run(panel_bundle(client), _PROBE)


class TestPanelBehaviour:

    def test_the_syslog_widget_names_the_host(self, out):
        assert 'sw-core-01' in out['syslogHost']

    def test_a_device_saved_twice_is_created_once(self, out):
        assert out['device'] == [1, 1]

    def test_a_webhook_or_channel_saved_twice_is_created_once(self, out):
        assert out['notify'] == 2          # one webhook POST + one channel POST

    def test_device_logs_keep_the_newest_answer(self, out):
        assert out['devlogs'] == ['new']

    def test_cluster_logs_keep_the_newest_answer(self, out):
        assert out['cllogs'] == [True, False]

    def test_leaving_status_early_leaves_no_poll(self, out):
        assert out['poll'] == [0, None]
        assert out['pollStarts'] == 1

    def test_the_interval_save_sees_a_refusal(self, out):
        assert out['interval'] == [False, ['danger']]

    def test_history_and_syslog_links_stay_in_the_spa(self, out):
        assert out['nav'] == [['#tab-history', '#tab-syslog'], '']

    def test_without_the_pane_it_navigates(self, out):
        assert out['navAway'] == '/history?module=a&key=b'

    def test_resize_listeners_do_not_stack(self, out):
        assert out['resize'] == 2


class TestServedMarkup:

    def test_no_outline_buttons_anywhere_in_the_panel(self, client):
        """CLAUDE.md: solid variants only. The DCIM guard only read DCIM; this reads it all."""
        for url in ('/admin', '/status', '/login'):
            assert 'btn-outline' not in client.get(url).get_data(as_text=True), url

    def test_a_disabled_series_is_disabled_not_just_unclickable(self, client):
        """`pointer-events:none` stops the mouse and nothing else: Tab + Enter still toggled
        a series the compare view had refused."""
        js = panel_bundle(client)
        assert ";opacity:.4;pointer-events:none" not in js
        assert "${disabled ? ' disabled' : ''}" in js

    def test_toasts_are_not_escaped_twice(self, client):
        """`showToast` writes `textContent`; an `esc()` inside shows `&amp;` to the reader."""
        js = panel_bundle(client)
        malas = re.findall(r'showToast\((?:esc\(|`[^`]*\$\{esc\()', js)
        assert malas == []
