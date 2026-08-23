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

    def test_the_domain_edits_nothing(self):
        """`infra_view` must not become a way around the registry's permissions.

        The section grew one non-GET endpoint — "collect now", which runs this device's
        checks — and that is not an edit: it writes no record of its own, it produces the
        same check state and history a scheduler cycle produces, through the same executor.
        An endpoint that CHANGED something would be a second way to reach the registry, from
        a screen deliberately handed to people who may not reach it. Hence the shape of this
        test: the write verbs stay out, and the one POST is named rather than tolerated.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        for verb in ("'PUT'", "'DELETE'", "'PATCH'"):
            assert verb not in routes, f'a {verb} route appeared in a section that edits nothing'
        posts = re.findall(r"@app\.route\('([^']+)',\s*methods=\['POST'\]\)", routes)
        assert posts == ['/api/v1/infra/hosts/<uid>/collect'], (
            f'unexpected POST route(s) in the infrastructure section: {posts}')

    def test_collecting_has_its_own_permission(self):
        """Looking at a wall screen is not the same act as starting minutes of polling.

        Reading the fleet is granted to `viewer`; a button that makes forty devices get
        polled must not come with it, or "may look" quietly becomes "may make the panel
        work". The flag is `infra_collect`, and the route must be gated by it — not by
        `infra_view`, which is the mistake this test exists to catch.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        body = routes.split("methods=['POST']")[1].split('def ')[0]
        assert 'infra_collect_req' in body, 'the collect route is not gated by its own flag'
        assert 'infra_view_req' not in body, (
            'collecting rides on the permission that only lets you look')
        assert "wa._perm_required('infra_collect')" in routes

    def test_the_flag_is_declared_and_not_handed_to_viewer(self):
        manifest = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'manifest.py'))
        m = re.search(r"\{'flag': 'infra_collect',\s*'roles':\s*\(([^)]*)\)", manifest)
        assert m, 'infra_collect is not declared in the domain manifest'
        roles = {r.strip().strip("'\"") for r in m.group(1).split(',') if r.strip()}
        assert roles == {'editor'}, (
            f'infra_collect is granted to {roles or "nobody"}; it mirrors checks_run, which is '
            'editor-only — a viewer must not be able to start a collection')

    def test_the_button_is_gated_too(self):
        """The endpoint is the gate; the button is only where it is OFFERED. Both, though:
        a button that 403s is a panel telling somebody to try again."""
        render = _read(os.path.join(INFRA, '_render.html'))
        assert "perms.has('infra_collect')" in render
        assert 'canCollect ?' in render, 'the button is drawn for everyone'

    def test_collecting_runs_whole_modules(self):
        """A run narrowed to one machine's items would report one machine's keys — and the
        monitor prunes, from the state it just wrote, every key the run did not report
        (`monitor._prune_orphan_status`). One device refreshed, thirty-nine wiped."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        assert '_prune_orphan_status' in routes, (
            'the reason whole modules are run is not written down where somebody would '
            'narrow it to one host')
        assert 'wa._run_checks(' in _read(os.path.join(SRC, 'lib', 'core', 'infra', 'jobs.py')), (
            'collecting does not go through the shared executor — a second implementation of '
            '"run a check and record it" is a second answer to what a result means')


class TestWatchingItHappen:
    """A collection runs for minutes and a bar that only moves at the end is
    indistinguishable from one that has hung. Three properties, and all three were the same
    complaint: say what it is doing, let the dialog be closed, and keep answering afterwards.
    """

    def _collect(self) -> str:
        return _read(os.path.join(INFRA, '_collect.html'))

    def test_the_partial_is_in_the_bundle(self):
        """A section's JavaScript exists only if the bundle includes it, and the failure is a
        button whose handler is not defined — silent until somebody presses it."""
        src = _read(BUNDLE)
        assert 'partials/infra/_collect.html' in src

    def test_the_request_hands_back_a_job_and_not_results(self):
        """Held open for the minutes a NAS takes, the request is one a browser or a reverse
        proxy gives up on — and the operator is left unable to tell whether it worked."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        body = routes.split("methods=['POST']")[1].split('@app.route')[0]
        assert "'job_id': job_id" in body
        assert 'start_collect(' in body
        assert '/api/v1/infra/collect/<job_id>' in routes, 'nothing can be asked about it'

    def test_the_progress_route_is_narrowed_to_the_job_s_host(self):
        """A job id is a short random string, and "hard to guess" is not a permission: without
        this, anyone who may poll learns the NAME of a machine they may not see."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        # [-1]: the path is named twice — in the module header and on the decorator —
        # and the half that matters is the one after the LAST of them.
        body = routes.split('/api/v1/infra/collect/<job_id>')[-1]
        assert "_may_see(job.get('host')" in body

    def test_closing_the_dialog_does_not_stop_the_run(self):
        """The whole reason the work is a thread on the server: nothing about it depends on
        somebody watching. The dialog closing must therefore touch the DISPLAY only."""
        src = self._collect()
        closed = src.split('hidden.bs.modal')[1].split('{once: true});')[0]
        assert '_infraCollectShown = false' in closed
        for word in ('abort', 'cancel', 'clearInterval', '_infraCollectJob = null'):
            assert word not in closed, (
                f'closing the dialog does something to the run itself ({word})')

    def test_there_is_still_a_bar_once_it_is_closed(self):
        """"Is it still going?" has to be answerable without reopening anything."""
        src = self._collect()
        body = src.split('function _infraCollectSlotHtml')[1].split(chr(10) + 'function ')[0]
        assert 'progress-bar' in body and '_infraCollectPct(job)' in body
        assert '_infraCollectOpen()' in body, 'the bar cannot be opened again'

    def test_the_bar_belongs_to_its_own_machine(self):
        """A run started on one device must not draw its progress over another's header."""
        body = self._collect().split('function _infraCollectSlotHtml')[1].split(chr(10) + 'function ')[0]
        assert 'job.host !== uid' in body

    def test_the_percentage_is_never_alone(self):
        """Progress is per MODULE, so nine fast ones and an SNMP profile reach 90 % in two
        seconds and stay there for four minutes. The name of what is working is what makes
        that pause legible; a bar on its own reads as a hang."""
        src = self._collect()
        assert 'running.detail || running.module' in src, (
            'the bar does not name what is working')
        assert '_infraCollectRow' in src, 'the dialog does not list the modules'

    def test_a_timeout_is_not_drawn_as_a_failure(self):
        """The module has not failed — it is still working and writes its own state and
        history when it lands. A red cross is a thing the screen has to take back."""
        row = self._collect().split('function _infraCollectRow')[1].split(chr(10) + 'function ')[0]
        assert "timeout: ['bi-hourglass-split',    'text-warning'" in row

    def test_a_running_module_says_what_it_is_doing(self):
        """0 % for five minutes is the same picture as a hang. The module boundary is all the
        core can see, so the module speaks for itself — and the screen has to draw what it
        said, in the dialog and on the bar."""
        src = self._collect()
        row = src.split('function _infraCollectRow')[1].split(chr(10) + 'function ')[0]
        assert "m.state === 'running' ? (m.detail" in row, (
            'a running module shows no detail — the dialog is a spinner with a name on it')
        bar = src.split('function _infraCollectSlotHtml')[1].split(chr(10) + 'function ')[0]
        assert 'running.detail' in bar, 'the bar does not say what is happening'

    def test_the_poll_gives_up_on_a_job_that_is_gone(self):
        """The jobs live in the panel's memory. After a restart, waiting longer does not
        bring one back — and a spinner that never stops is worse than an answer."""
        body = self._collect().split('async function _infraCollectPoll')[1].split(chr(10) + 'function ')[0]
        assert 'infra_collect_unknown_job' in body
        assert 'return;' in body

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


class TestItRefreshesWithoutBlinking:
    """Reported from the panel: the refresh button made the whole page blink.

    It went through the section's ENTRY POINT, which re-asks for the fleet, then blanks the
    pane for a spinner, then asks for the device: two round trips and an empty screen to
    redraw one machine. On a wall display with the auto-refresh on, that is every interval.
    """

    def _render(self) -> str:
        return _read(os.path.join(INFRA, '_render.html'))

    def test_the_button_refreshes_in_place(self):
        src = self._render()
        assert 'onclick="_infraReload()"' in src
        assert 'onclick="_infraDetail=null;renderInfra()"' not in src, (
            'the refresh button still goes through the entry point, which blanks the pane')

    def test_it_swaps_the_markup_only_once_the_answer_is_in_hand(self):
        body = self._render().split('async function _infraReload(')[1].split(chr(10) + '}')[0]
        assert body.index('await apiGet') < body.index('innerHTML'), (
            'the pane is written before the data arrives — which is the blink')
        assert 'if (!data) return;' in body, (
            'a failed refresh throws away the screen it had')

    def test_the_tick_uses_it_too(self):
        """The auto-refresh is the control this section carries FOR wall screens. Blinking
        every interval is the one thing it must not do."""
        body = self._render().split('function _infraAutoTick(')[1].split(chr(10) + '}')[0]
        assert '_infraReload()' in body

    def test_the_spinner_is_for_an_empty_pane(self):
        """Opening a device from the list, or a reload landing straight on one. Painting it
        over a device already on screen is the blink itself."""
        body = self._render().split('async function _infraOpenView(')[1].split(chr(10) + '}')[0]
        assert "querySelector('.ss-vfill')" in body

    def test_the_reload_button_does_not_call_a_device_a_server(self):
        """`refresh_tt` is "Reload data from server" and it is right everywhere else. Beside a
        machine it reads as the machine — and the distinction that matters in this header is
        the other one: this button does not poll the equipment, and the one next to it does."""
        assert "t('infra_reload_tt')" in self._render()
        assert "t('refresh_tt')" not in self._render()


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
