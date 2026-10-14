#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The reader's own order of the left menu ("Customise menu").

Saved per user on the server — ``sidebar_order`` in ``PUT /api/v1/users/me/preferences``,
served back by ``/api/v1/me`` — as the entries' stable keys. Pinned here: the round trip and
the reset, the bounds the server puts on the record, that nobody writes somebody else's, and
the client side in ``node``: the merge with the default order (a new entry lands where it
would have been, a retired key is ignored, a hidden entry stays hidden), the menu redrawn in a
saved order, and the editing mode's controls.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile

import pytest

from tests.conftest import _login, _login_as                        # noqa: E402
from tests.helpers import node_run, panel_bundle                    # noqa: E402

try:
    import flask                                                    # noqa: F401
    _HAS_FLASK = True
except ImportError:                                                 # pragma: no cover
    _HAS_FLASK = False

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask not installed')

_URL = '/api/v1/users/me/preferences'
_ORDER = {'top': ['g:system', 'p:overview', 'g:catalog'],
          'groups': {'system': ['t:services', 't:audit'], 'catalog': ['t:credentials']}}


def _put(c, body):
    return c.put(_URL, data=json.dumps(body), content_type='application/json')


# ── the API ───────────────────────────────────────────────────────────────────────────────

class TestSaveReadReset:

    def test_saved_order_comes_back_from_me_and_reaches_the_store(self, admin, client):
        _login(client)
        assert client.get('/api/v1/me').get_json()['sidebar_order'] is None
        r = _put(client, {'sidebar_order': _ORDER})
        assert r.status_code == 200, r.get_json()
        assert client.get('/api/v1/me').get_json()['sidebar_order'] == _ORDER
        # On the server, not in the browser: a fresh read of the users table holds it.
        admin._users = {}
        admin._load_users()
        assert admin._users['admin']['sidebar_order'] == _ORDER

    def test_reset_removes_the_preference(self, admin, client):
        _login(client)
        assert _put(client, {'sidebar_order': _ORDER}).status_code == 200
        for empty in (None, {}):
            assert _put(client, {'sidebar_order': _ORDER}).status_code == 200
            assert _put(client, {'sidebar_order': empty}).status_code == 200
            assert client.get('/api/v1/me').get_json()['sidebar_order'] is None
            assert 'sidebar_order' not in admin._users['admin']

    def test_duplicates_are_dropped_and_empty_groups_not_kept(self, client):
        _login(client)
        body = {'top': ['p:a', 'p:b', 'p:a'], 'groups': {'system': ['t:x', 't:x'], 'catalog': []}}
        assert _put(client, {'sidebar_order': body}).status_code == 200
        got = client.get('/api/v1/me').get_json()['sidebar_order']
        assert got == {'top': ['p:a', 'p:b'], 'groups': {'system': ['t:x']}}

    def test_saving_the_order_is_audited_as_a_preference_change(self, admin, client):
        seen = []
        admin._audit = lambda ev, *a, **kw: seen.append((ev, kw.get('detail')))
        _login(client)
        _put(client, {'sidebar_order': _ORDER})
        ev = [d for e, d in seen if e == 'user_preferences_changed']
        assert ev and ev[-1]['changes']['sidebar_order'] == {'old': 'default', 'new': 'custom'}


_BAD = [
    pytest.param(['p:a'], id='a-list-not-an-object'),
    pytest.param('p:a', id='a-string'),
    pytest.param({'top': ['p:a'], 'extra': []}, id='unknown-field'),
    pytest.param({'top': 'p:a'}, id='top-not-a-list'),
    pytest.param({'top': [1, 2]}, id='non-string-key'),
    pytest.param({'top': ['<script>']}, id='bad-key-characters'),
    pytest.param({'top': ['p:' + 'x' * 64]}, id='key-too-long'),
    pytest.param({'top': [f'p:{i}' for i in range(201)]}, id='too-many-entries'),
    pytest.param({'groups': ['t:a']}, id='groups-not-an-object'),
    pytest.param({'groups': {'bad group': ['t:a']}}, id='bad-group-name'),
    pytest.param({'groups': {f'g{i}': ['t:a'] for i in range(17)}}, id='too-many-groups'),
    pytest.param({'groups': {'system': 't:a'}}, id='group-not-a-list'),
    pytest.param({'groups': {f'g{i}': [f't:{i}-{j}-' + 'y' * 50 for j in range(150)]
                             for i in range(3)}}, id='oversize'),
]


class TestValidation:

    @pytest.mark.parametrize('bad', _BAD)
    def test_a_malformed_or_oversize_order_is_refused(self, admin, client, bad):
        _login(client)
        r = _put(client, {'sidebar_order': bad})
        assert r.status_code == 400, (bad, r.get_json())
        assert 'sidebar_order' not in admin._users['admin']

    def test_a_refusal_applies_nothing_else_of_the_same_request(self, admin, client):
        _login(client)
        r = _put(client, {'lang': 'en_EN', 'sidebar_order': {'top': ['<x>']}})
        assert r.status_code == 400
        assert admin._users['admin'].get('lang', '') != 'en_EN'

    def test_signed_out_cannot_write(self, client):
        assert _put(client, {'sidebar_order': _ORDER}).status_code in (302, 401)


class TestOwnRecordOnly:

    def test_each_user_writes_and_reads_their_own(self, admin, client):
        bob = _login_as(admin, 'bob', perms=['overview_view'])
        assert _put(bob, {'sidebar_order': _ORDER}).status_code == 200
        assert admin._users['bob']['sidebar_order'] == _ORDER
        _login(client)
        assert 'sidebar_order' not in admin._users['admin']
        assert client.get('/api/v1/me').get_json()['sidebar_order'] is None
        assert bob.get('/api/v1/me').get_json()['sidebar_order'] == _ORDER

    def test_there_is_no_way_to_set_another_users_order(self, admin, client):
        _login_as(admin, 'carol', perms=['overview_view'])
        _login(client)
        # The account editor of the admin takes named fields, and this is not one of them.
        client.put('/api/v1/users/carol', data=json.dumps({'sidebar_order': _ORDER}),
                   content_type='application/json')
        assert 'sidebar_order' not in admin._users['carol']
        # And the preferences endpoint has no "whose" — it is `me`, always.
        r = client.put('/api/v1/users/carol/preferences', data=json.dumps({'sidebar_order': _ORDER}),
                       content_type='application/json')
        assert r.status_code in (404, 405)
        assert 'sidebar_order' not in admin._users['carol']


# ── the markup ────────────────────────────────────────────────────────────────────────────

class TestMarkup:

    def test_every_reorderable_entry_carries_a_stable_key(self, client):
        _login(client)
        html = client.get('/admin').get_data(as_text=True)
        side = html[html.index('id="ss-sidebar"'):html.index('</aside>')]
        tops = re.findall(r'id="nav-page-([\w-]+)-li"[^>]*data-sb-key="p:([\w-]+)"', side)
        assert tops and all(a == b for a, b in tops)
        assert 'data-sb-key="g:system"' in side and 'data-sb-key="g:catalog"' in side
        assert 'data-sb-group="system"' in side and 'data-sb-group="catalog"' in side
        tabs = re.findall(r'id="tab-([\w-]+)-li"[^>]*data-sb-key="t:([\w-]+)"', side)
        assert tabs and all(a == b for a, b in tabs)
        # Every entry of a group list is keyed — one without a key would be pinned in place.
        assert side.count('id="tab-') - side.count('id="tab-account') >= len(tabs)

    def test_the_mode_is_reached_from_the_sidebar_with_solid_buttons(self, client):
        _login(client)
        html = client.get('/admin').get_data(as_text=True)
        side = html[html.index('id="ss-sidebar"'):html.index('</aside>')]
        assert 'onclick="_sbOrderEdit()"' in side
        bar = side[side.index('id="ss-sb-editbar"'):]
        bar = bar[:bar.index('<!-- Navigation -->')]
        for fn in ('_sbOrderSave()', '_sbOrderCancel()', '_sbOrderReset()'):
            assert fn in bar
        assert 'btn-outline' not in bar
        assert 'confirm(' not in bar

    def test_while_arranging_a_click_is_stopped_before_bootstrap_sees_it(self, client):
        # Bootstrap delegates its tab/collapse handlers to the document IN THE CAPTURE PHASE,
        # so a guard registered on the sidebar ran after the tab had switched: clicking an
        # entry to drag it navigated away. Seen in the browser; only the window comes first.
        _login(client)
        js = panel_bundle(client)
        wire = js[js.index('function _sbWireEditing'):]
        wire = wire[:wire.index('let dragged')]
        assert "window.addEventListener('click'" in wire
        assert '}, true);' in wire                    # the capture phase

    def test_on_a_phone_the_user_button_does_not_close_the_drawer(self, client):
        # The user menu (and with it "Customise menu") lives inside the drawer: closing the
        # drawer on the user button's click slid the menu off-screen before it could be used.
        _login(client)
        js = panel_bundle(client)
        line = [ln for ln in js.splitlines() if '_sbIsMobile() && e.target.closest(' in ln
                and '_closeSidebar()' in ln]
        assert line and all(':not(.ss-sb-userbtn)' in ln for ln in line)

    def test_the_saved_order_is_applied_before_the_menu_is_revealed(self, client):
        _login(client)
        js = panel_bundle(client)
        i = js.index('_sbApplyOrder(currentUser.sidebar_order)')
        assert i < js.index('applyRoleRestrictions();', i)
        assert js.index("currentUser = await apiGet('/api/v1/me')") < i


# ── the client, in node ───────────────────────────────────────────────────────────────────

_PROBE = r"""
__out = {};
// Merge: the reader's order, with what it does not know placed by its default neighbours.
const M = _sbMergeOrder;
__out.merge = {
    nothing_saved: M(['a', 'b', 'c'], null),
    full: M(['a', 'b', 'c'], ['c', 'a', 'b']),
    new_after_its_neighbour: M(['a', 'b', 'c', 'd'], ['d', 'b', 'a']),
    new_first: M(['x', 'a', 'b'], ['b', 'a']),
    new_run: M(['a', 'n1', 'n2', 'b'], ['b', 'a']),
    retired_ignored: M(['a', 'b'], ['gone', 'b', 'a', 'gone2']),
    dupes: M(['a', 'b'], ['b', 'b', 'a']),
    junk: M(['a', 'b'], 'nope'),
};

// A tiny list that really reorders: children, insertBefore, siblings.
function li(key, hidden, label) {
    const n = {dataset: key ? {sbKey: key} : {}, style: {display: hidden ? 'none' : ''},
               classList: {contains: () => false}, parentElement: null, label: label || key,
               querySelector: (s) => (s === '.ss-sb-label' ? {textContent: label || key} : null)};
    return n;
}
function list(items, group) {
    const ul = {children: [], dataset: group ? {sbGroup: group} : {}};
    const sync = () => ul.children.forEach((c, i) => {
        c.parentElement = ul;
        c.previousElementSibling = ul.children[i - 1] || null;
        c.nextElementSibling = ul.children[i + 1] || null;
        c.nextSibling = c.nextElementSibling;
    });
    ul.insertBefore = (n, ref) => {
        const k = ul.children.indexOf(n);
        if (k >= 0) ul.children.splice(k, 1);
        const at = ref ? ul.children.indexOf(ref) : -1;
        if (at < 0) ul.children.push(n); else ul.children.splice(at, 0, n);
        sync();
    };
    items.forEach(n => ul.children.push(n));
    sync();
    return ul;
}
const acct = li(null);                                  // the hidden Account trigger
const top = list([li('p:overview'), li('p:history'), li('p:secret', true),
                  li('g:catalog'), li('g:system'), acct]);
const sys = list([li('t:audit'), li('t:backup'), li('t:config', true), li('t:services')], 'system');
const qs = document.querySelector, qsa = document.querySelectorAll;
document.querySelector = (s) => (s === '#ss-sidebar .ss-sb-list' ? top : qs(s));
document.querySelectorAll = (s) => (s === '#ss-sidebar [data-sb-group]' ? [sys] : qsa(s));
const keys = (ul) => ul.children.map(c => c.dataset.sbKey || '(acct)');
const shown = (ul) => ul.children.filter(c => c.style.display !== 'none').map(c => c.dataset.sbKey || '(acct)');
_sbCaptureDefault();                                    // as at page load

__out.default_is_null = _sbCurrentOrder();
// A saved order from before `p:history` and `t:backup` existed, naming a retired section.
_sbApplyOrder({top: ['g:system', 'p:secret', 'p:retired', 'p:overview', 'g:catalog'],
               groups: {system: ['t:services', 't:config', 't:audit'], other: ['t:x']}});
__out.applied = {top: keys(top), sys: keys(sys), top_shown: shown(top), sys_shown: shown(sys)};
__out.current = _sbCurrentOrder();
// Moving with the arrows steps over the hidden entries; at the edge it goes nowhere.
const svc = sys.children[0];                            // t:services
__out.move_down = [_sbMove(svc, 1), keys(sys)];         // over hidden t:config, past t:audit
__out.move_up_edge = [_sbMove(sys.children[1], -1), keys(sys)];   // t:audit, under hidden t:config
// Back to the default.
_sbApplyOrder(null);
__out.reset = {top: keys(top), sys: keys(sys), current: _sbCurrentOrder()};
// The editing mode's controls: a grip and an arrow each way, each saying what it moves.
const ctl = _sbControlsHtml(li('t:audit', false, 'Auditoría'));
__out.ctl = ctl;
__out.says = [tf('sb_order_up', 'Auditoría'), tf('sb_order_down', 'Auditoría')];
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
def out():
    if shutil.which(os.environ.get('SS_NODE') or 'node') is None:
        pytest.skip('no node: nothing to run the script with')
    c = _make_wa().app.test_client()
    _login(c)
    return node_run(panel_bundle(c), _PROBE)


class TestMergeInNode:

    def test_without_a_saved_order_the_default_stands(self, out):
        assert out['merge']['nothing_saved'] == ['a', 'b', 'c']
        assert out['merge']['junk'] == ['a', 'b']
        assert out['merge']['full'] == ['c', 'a', 'b']

    def test_an_entry_the_saved_order_does_not_know_keeps_its_default_place(self, out):
        assert out['merge']['new_after_its_neighbour'] == ['d', 'b', 'c', 'a']
        assert out['merge']['new_first'] == ['x', 'b', 'a']
        assert out['merge']['new_run'] == ['b', 'a', 'n1', 'n2']

    def test_retired_keys_and_duplicates_are_ignored(self, out):
        assert out['merge']['retired_ignored'] == ['b', 'a']
        assert out['merge']['dupes'] == ['b', 'a']


class TestMenuInNode:

    def test_the_menu_is_redrawn_in_the_saved_order(self, out):
        a = out['applied']
        # p:history is new → after p:overview, its default predecessor; the retired key is
        # ignored; the Account trigger stays last.
        assert a['top'] == ['g:system', 'p:secret', 'p:overview', 'p:history', 'g:catalog', '(acct)']
        # t:backup is new → after t:audit.
        assert a['sys'] == ['t:services', 't:config', 't:audit', 't:backup']

    def test_an_entry_hidden_by_permission_stays_hidden_wherever_it_lands(self, out):
        a = out['applied']
        assert 'p:secret' not in a['top_shown'] and 'p:secret' in a['top']
        assert 't:config' not in a['sys_shown'] and 't:config' in a['sys']

    def test_the_default_order_is_saved_as_nothing(self, out):
        assert out['default_is_null'] is None
        assert out['reset']['current'] is None
        assert out['reset']['top'] == ['p:overview', 'p:history', 'p:secret', 'g:catalog',
                                       'g:system', '(acct)']
        assert out['reset']['sys'] == ['t:audit', 't:backup', 't:config', 't:services']

    def test_what_is_saved_is_every_key_in_the_order_on_screen(self, out):
        cur = out['current']
        assert cur['top'] == ['g:system', 'p:secret', 'p:overview', 'p:history', 'g:catalog']
        assert cur['groups'] == {'system': ['t:services', 't:config', 't:audit', 't:backup']}

    def test_the_arrows_step_over_hidden_entries_and_stop_at_the_edge(self, out):
        moved, keys = out['move_down']
        assert moved is True
        assert keys == ['t:config', 't:audit', 't:services', 't:backup']
        moved, keys = out['move_up_edge']
        assert moved is False                       # only the hidden t:config is above
        assert keys == ['t:config', 't:audit', 't:services', 't:backup']

    def test_edit_mode_draws_up_and_down_buttons_naming_the_entry(self, out):
        ctl = out['ctl']
        assert ctl.count('ss-sb-mv') == 2
        assert 'data-sb-dir="-1"' in ctl and 'data-sb-dir="1"' in ctl
        up, down = out['says']
        assert 'Auditoría' in up and 'sb_order' not in up and up != down
        assert f'aria-label="{up}"' in ctl and f'aria-label="{down}"' in ctl
        assert 'btn-secondary' in ctl and 'btn-outline' not in ctl
