#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Infrastructure (/infra) — the wiring a root section needs to exist at all.

A section of this panel is not one file. It is an entry in the page registry (which is what
gives it a URL, a route, a permission gate and a sidebar item), a pane in the shell to render
into, its JavaScript in the bundle, and a render function whose name the registry names. Miss
the registry entry and there is no URL; miss the pane and the section opens onto nothing; miss
the include and the sidebar offers a section whose renderer is not defined. Every one of them
fails silently, and none in a way a Python test would otherwise notice.

The rest of this file pins the two properties that make it a SECTION and not a second copy of
System › Infrastructure: it is read-only, and it never carries what it does not show.
"""

import io
import os
import re

from tests.helpers import _read

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
TPL = os.path.join(SRC, 'lib', 'web_admin', 'templates')
INFRA = os.path.join(TPL, 'partials', 'infra')
BUNDLE = os.path.join(TPL, 'partials', '_js_sections.html')
CONSTANTS = os.path.join(SRC, 'lib', 'web_admin', 'constants.py')
ROUTES_INDEX = os.path.join(SRC, 'lib', 'web_admin', 'routes', '__init__.py')


class TestTheSectionIsWiredEndToEnd:

    def test_it_is_in_the_page_registry(self):
        """One entry is what gives a core section its URL, its route, its permission gate and
        its sidebar item — see routes/pages.py, which builds all four from this."""
        src = _read(CONSTANTS)
        assert "'id': 'infra'" in src and "'url': '/infra'" in src
        assert "'perm': 'infra_view'" in src
        assert "'render': 'renderInfra'" in src
        assert "'pane': 'tab-infra'" in src

    def test_the_shell_has_a_pane_to_render_into(self):
        dash = _read(os.path.join(TPL, 'dashboard.html'))
        assert 'partials/infra/_pane.html' in dash
        assert "standalone == 'infra'" in dash, (
            'the pane is not activated when /infra is served on its own URL')
        assert 'id="infra-container"' in _read(os.path.join(INFRA, '_pane.html'))

    def test_its_javascript_is_included(self):
        src = _read(BUNDLE)
        for part in ('partials/infra/_views.html', 'partials/infra/_render.html',
                     'partials/infra/_list.html'):
            assert part in src, f'{part} is never included — the section stays empty'

    def test_the_render_the_registry_names_exists(self):
        assert 'function renderInfra(' in _read(os.path.join(INFRA, '_render.html'))

    def test_its_routes_are_registered(self):
        src = _read(ROUTES_INDEX)
        assert 'from lib.core.infra.routes import register as _infra' in src
        assert '_infra(app, wa)' in src
        assert '/api/v1/infra' in src, 'the URL surface index does not mention it'


class TestItIsTheSharedMachinery:

    def test_the_fleet_is_built_by_the_factory(self):
        """Filter strip, column chooser, per-user persistence and pagination for free — and,
        more to the point, the same behaviour as every other list in the panel."""
        src = _read(os.path.join(INFRA, '_list.html'))
        assert 'createListTable(' in src and "key: 'infra'" in src
        assert 'persist: true' in src and 'filters:' in src

    def test_every_sortable_column_has_a_sort_value(self):
        src = _read(os.path.join(INFRA, '_list.html'))
        keys = set(re.findall(r"sortKey:\s*'([a-z_]+)'", src))
        body = src.split('sortValue:')[1].split('cell:')[0]
        missing = [k for k in keys if f"case '{k}'" not in body and k != 'name']
        assert not missing, f'sortable columns with no sort value: {missing}'

    def test_the_views_come_from_the_registry(self):
        views = _read(os.path.join(INFRA, '_views.html'))
        assert 'createViewState(' in views and 'INFRA_VIEWS' in views


class TestItShowsWithoutHandingOver:

    def test_the_payload_is_a_whitelist(self):
        """A projection written as "the record minus a few keys" is one added field away from
        shipping the bound credentials of every protocol that reaches the machine."""
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert '_HOST_FIELDS' in svc
        assert "'profiles'" not in svc, 'the projection names the credential bag'

    def test_the_domain_writes_nothing(self):
        """`infra_view` must not become a way around the registry's permissions."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        for verb in ("'POST'", "'PUT'", "'DELETE'", "'PATCH'"):
            assert verb not in routes, f'a {verb} route appeared in a read-only section'

    def test_it_owns_no_store(self):
        """Every fact it shows belongs to somebody — hosts, check state, history. A fourth
        copy would be a fourth thing to keep in step, and the first to drift would be the one
        people are watching."""
        assert not os.path.exists(os.path.join(SRC, 'lib', 'core', 'infra', 'store.py'))

    def test_the_state_vocabulary_is_the_registry_s(self):
        """One vocabulary for "how is this machine": the section renders `ok/warning/error`
        and the empty string, which is what `hosts.service._host_statuses` produces. A second
        set of names would be a second definition of a broken host."""
        render = _read(os.path.join(INFRA, '_render.html'))
        body = render.split('function _infraStateBadge')[1].split('function ')[0]
        for state in ('ok:', 'warning:', 'error:'):
            assert state in body
        assert 'infra_unwatched' in body, 'a host nobody watches has no state of its own'


class TestItDoesNotGoStale:
    """Reported from the panel: a machine added in System did not appear here.

    The first version fetched the fleet only when it had nothing, which is the cache a section
    gets away with while it is the only thing that writes its own data. This one writes NONE
    of it — every fact on the screen is edited somewhere else, so "I already have a fleet" is
    never a reason to believe it is the current one.
    """

    def _render(self) -> str:
        return _read(os.path.join(INFRA, '_render.html'))

    def test_opening_the_section_asks_the_server(self):
        body = self._render().split('async function renderInfra(')[1].split('\n}')[0]
        assert "apiGet('/api/v1/infra/hosts')" in body
        assert '_infraHosts.length' not in body, (
            'the entry point serves a cached fleet again — a host added in System would not '
            'appear until somebody pressed Refresh')

    def test_the_cheap_redraws_do_not_hit_the_network(self):
        """A filter, a sort and a page change go through the factory's own render. If those
        refetched, every keystroke in the filter box would be a request."""
        assert '_infraRender()' in self._render()

    def test_it_carries_the_shared_auto_refresh_control(self):
        """Not a hardcoded interval: this is the screen somebody leaves open on a wall, and
        how stale it may be is a decision about the room. The panel already owns that decision
        as a control, with its own persistence and the same menu in five other sections."""
        src = _read(os.path.join(INFRA, '_list.html'))
        assert '_autoRefreshControl(' in src
        assert "setFn: 'setInfraAutoRefresh'" in src

    def test_the_tick_stops_when_the_section_is_not_on_screen(self):
        """A timer polling a hidden pane is traffic for nobody."""
        body = self._render().split('function _infraAutoTick(')[1].split('\n}')[0]
        assert "getElementById('tab-infra')" in body and "classList.contains('active')" in body

    def test_the_chosen_interval_survives_a_reload(self):
        src = self._render()
        assert "localStorage.setItem('ss_infra_auto'" in src
        assert "localStorage.getItem('ss_infra_auto'" in src
