#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module-contributed top-level pages (``schema.json`` → ``__page__``).

A watchful may claim a section of its own beside Overview / History / Syslog. The core
must stay module-agnostic: it reads generic keys, merges them into the page registry and
renders a pane + a sidebar entry; the module supplies the label, the data hook and (if it
wants) the renderer. These tests pin that contract.
"""

import pytest

from lib.modules.discovery.pages import _page_spec, module_pages_catalog

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login


class TestNormalize:
    """One malformed declaration must never break the panel — the section just does
    not appear (the same doctrine as every other discovery mechanism)."""

    def test_defaults_are_applied(self):
        spec = _page_spec('mymod', {})
        assert spec['id'] == 'mymod'                 # id defaults to the module name
        assert spec['perm'] == 'modules_view'        # watchfuls own no permission flags
        assert spec['render'] == '' and spec['order'] == 100

    def test_explicit_values_win(self):
        spec = _page_spec('mymod', {'id': 'cloud', 'icon': 'bi-cloud', 'order': 5,
                                    'render': 'renderCloud', 'perm': 'modules_view'})
        assert (spec['id'], spec['icon'], spec['order'], spec['render']) == \
               ('cloud', 'bi-cloud', 5, 'renderCloud')

    @pytest.mark.parametrize('bad', ['Bad Id', 'has-dash', '9lives', 'x/y', 'ñ'])
    def test_an_unusable_id_is_dropped(self, bad):
        """The id becomes a URL, an element id and a tab target."""
        assert _page_spec('mymod', {'id': bad}) is None

    def test_a_blank_id_falls_back_to_the_module_name(self):
        """Blank means "name it after me", as it does for a module's Overview widget —
        not "invalid"."""
        assert _page_spec('mymod', {'id': ''})['id'] == 'mymod'

    @pytest.mark.parametrize('reserved', ['admin', 'overview', 'history', 'syslog',
                                          'status', 'account', 'login'])
    def test_core_ids_cannot_be_shadowed(self, reserved):
        """A module claiming /admin or /overview would hijack a core route."""
        assert _page_spec('mymod', {'id': reserved}) is None

    def test_a_non_dict_declaration_is_dropped(self):
        assert _page_spec('mymod', 'nope') is None
        assert _page_spec('mymod', None) is None


class TestDiscovery:

    def test_a_real_module_contributes_a_page(self):
        """m365 declares one — proves the pipeline works on a shipped module."""
        pages = module_pages_catalog()
        m365 = next((p for p in pages if p['module'] == 'm365'), None)
        assert m365, 'm365 declares __page__ but no page was discovered'
        assert m365['id'] == 'm365'

    def test_a_page_can_decline_to_ship_a_renderer(self):
        """The interesting half of the mechanism, and the one m365 now exercises: with no
        `render`, the core paints whatever page_data returned. m365 used to ship its own
        renderer, which had drifted into a stale copy of the core's — it had lost the
        group-by the core gained — so it was dropped rather than kept in step by hand."""
        m365 = next(p for p in module_pages_catalog() if p['module'] == 'm365')
        assert m365['render'] == '', 'm365 ships a renderer again; the core already has one'
        assert m365['refresh'] == 'page_refresh',             'without a refresh action the page can only ever show the cached result'

    def test_every_page_carries_what_the_core_needs(self):
        for p in module_pages_catalog():
            for key in ('id', 'module', 'icon', 'order', 'perm', 'label_i18n'):
                assert p.get(key) not in (None, ''), f"{p.get('module')} page missing {key}"
            assert isinstance(p['label_i18n'], dict) and p['label_i18n']

    def test_a_declared_refresh_reaches_the_client_spec(self):
        """`refresh` is what tells the core's generic renderer the module can fetch live
        data — and therefore whether to offer the button at all. Dropped on the way to the
        client, a module that declares one silently gets no refresh button, while a module
        shipping its own renderer still has one: the same declaration, two behaviours."""
        from lib.web_admin.constants import _module_home_pages
        declared = {p['module']: p['refresh'] for p in module_pages_catalog()}
        assert any(declared.values()), 'no module declares a refresh — test is vacuous'
        for page in _module_home_pages():
            assert page['standalone']['refresh'] == declared[page['module']]

    def test_pages_are_ordered_and_unique(self):
        pages = module_pages_catalog()
        assert [p['order'] for p in pages] == sorted(p['order'] for p in pages)
        ids = [p['id'] for p in pages]
        assert len(ids) == len(set(ids)), 'two modules claim the same page id'

    def test_the_label_is_the_module_s_own_pretty_name(self):
        """The core owns no string naming a module."""
        m365 = next(p for p in module_pages_catalog() if p['module'] == 'm365')
        assert m365['label_i18n'].get('en_EN') == 'Microsoft 365'

    def test_a_missing_watchfuls_dir_is_not_an_error(self):
        assert module_pages_catalog('/nonexistent/path') == []


class TestRegistryMerge:

    def test_the_page_joins_the_landing_registry(self):
        from lib.web_admin.constants import home_page_ids, standalone_pages
        assert 'm365' in home_page_ids(), 'a module page must be selectable as a landing page'
        page = next(p for p in standalone_pages() if p['id'] == 'm365')
        assert page['url'] == '/m365'
        assert page['standalone']['pane'] == 'tab-m365'
        assert page['standalone']['label_i18n']          # module-owned label, not a core key

    def test_core_pages_are_untouched(self):
        from lib.web_admin.constants import standalone_pages
        core = {p['id'] for p in standalone_pages() if not p.get('module')}
        assert {'overview', 'history', 'syslog'} <= core


@pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')
class TestServed:
    """The section must be reachable and rendered without web_admin naming the module."""

    def test_its_url_is_routed(self, client):
        _login(client)
        assert client.get('/m365').status_code == 200

    def test_the_url_requires_a_session(self, client):
        resp = client.get('/m365')
        assert resp.status_code in (301, 302) and '/login' in resp.headers.get('Location', '')

    def test_the_shell_carries_its_pane_and_sidebar_entry(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'id="tab-m365"' in html and 'id="m365-container"' in html
        assert 'id="btn-nav-m365"' in html and 'data-nav-url="/m365"' in html
        assert 'Microsoft 365' in html                      # the module's own label

    def test_a_module_shipped_ui_fragment_is_injected(self, client):
        """A module may still ship front-end of its own (web/_ui.html) and have it injected
        into the shell. Pinned on snmp, which genuinely does: m365 used to be the example
        here and no longer ships one, so keeping it as the example would have left this
        testing nothing."""
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'function _mibStatusBadge' in html

    def test_the_core_renderer_is_what_paints_m365(self, client):
        _login(client)
        html = client.get('/admin').data.decode('utf-8', 'replace')
        assert 'async function renderModulePage' in html
        assert 'renderM365Page' not in html, 'the retired renderer is back'

    def test_the_data_endpoint_answers(self, client):
        _login(client)
        r = client.get('/api/v1/modules/page/m365')
        assert r.status_code == 200
        body = r.get_json()
        assert body['module'] == 'm365' and isinstance(body['data'], dict)

    def test_a_module_without_a_page_is_404(self, client):
        """The declaration check is what stops this being a "run any module hook" hole."""
        _login(client)
        assert client.get('/api/v1/modules/page/ping').status_code == 404
        assert client.get('/api/v1/modules/page/Bad-Name').status_code == 400


class TestLiveRefreshWithoutAForm:
    """A module section asking for a live refresh knows only the item KEY.

    Actions were built for the module-config form, which posts the whole (possibly
    unsaved) item. A page has no form: without the server filling in the rest, the action
    would run against an empty item — no ``cred_uid``, so no credentials, so an
    authentication failure on a check that works everywhere else.
    """

    def _stored(self):
        return {'watchfuls.demo': {'list': {'k1': {
            'label': 'Prod', 'cred_uid': 'cred-1', 'enabled': True, 'timeout': 30}}}}

    def _fill(self, config, stored=None):
        from lib.core.modules import service as svc

        class _WA:
            _secret_keys = frozenset()

            def _load_modules(self):
                return stored if stored is not None else {}

        svc._fill_from_stored_item(_WA(), 'demo', config)
        return config

    def test_the_key_alone_is_enough(self):
        out = self._fill({'_item_key': 'k1'}, self._stored())
        assert out['cred_uid'] == 'cred-1' and out['label'] == 'Prod'

    def test_what_the_caller_sent_wins(self):
        """A form action posts the item being edited — those values are the point."""
        out = self._fill({'_item_key': 'k1', 'timeout': 5, 'label': ''}, self._stored())
        assert out['timeout'] == 5 and out['label'] == ''      # even a cleared field
        assert out['cred_uid'] == 'cred-1'                     # …and the rest still fills

    def test_an_unprefixed_module_key_is_found_too(self):
        stored = {'demo': {'list': {'k1': {'cred_uid': 'cred-1'}}}}
        assert self._fill({'_item_key': 'k1'}, stored)['cred_uid'] == 'cred-1'

    def test_no_key_and_unknown_key_change_nothing(self):
        assert self._fill({'a': 1}, self._stored()) == {'a': 1}
        assert self._fill({'_item_key': 'nope'}, self._stored()) == {'_item_key': 'nope'}

    def test_a_config_read_failure_is_not_fatal(self):
        """The action should still run on what the caller sent."""
        from lib.core.modules import service as svc

        class _Boom:
            def _load_modules(self):
                raise RuntimeError('db down')

        cfg = {'_item_key': 'k1'}
        svc._fill_from_stored_item(_Boom(), 'demo', cfg)
        assert cfg == {'_item_key': 'k1'}
