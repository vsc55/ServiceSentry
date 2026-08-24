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

from tests.helpers import _fn, _read, _strip_comments

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

    def test_the_domain_does_not_reach_the_registry(self):
        """`infra_view` must not become a way around the registry's permissions.

        This is not "the section is read-only" — it has two POSTs and both are deliberate:
        "collect now" runs this device's checks, which writes no record of its own and
        produces exactly what a scheduler cycle produces; "watch" sets one flag against one
        row. Neither stores a name, an address or a credential, and neither can create or
        delete a machine. THAT is the property: an endpoint that edited the registry would be
        a second way into it from a screen deliberately handed to people who may not reach it.

        So the write verbs stay out, every POST is named rather than tolerated, and each one
        carries a flag of its own — checked below.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        for verb in ("'PUT'", "'DELETE'", "'PATCH'"):
            assert verb not in routes, f'a {verb} route appeared in a section that edits nothing'
        posts = re.findall(r"@app\.route\('([^']+)',\s*methods=\['POST'\]\)", routes)
        assert sorted(posts) == sorted(['/api/v1/infra/hosts/<uid>/collect',
                                        '/api/v1/infra/hosts/<uid>/watch']), (
            f'unexpected POST route(s) in the infrastructure section: {posts}')
        # The registry's own write path is what must not be reachable from here.
        for call in ('.create(', '.update(', '.delete('):
            assert f'store{call}' not in routes, (
                f'the section calls store{call} — that is the registry, behind its own '
                'permission, and this screen is not it')

    def test_each_write_has_its_own_permission(self):
        """Looking at a wall screen is not the same act as starting minutes of polling, nor
        the same as deciding what wakes somebody up.

        Reading the fleet is granted to `viewer`; neither of those two must come with it, or
        "may look" quietly becomes "may make the panel work". Each POST is gated by a flag of
        its own — not by `infra_view`, which is the mistake this test exists to catch.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        for path, flag in (('/collect', 'infra_collect'), ('/watch', 'infra_watch')):
            body = routes.split(f"'/api/v1/infra/hosts/<uid>{path}'")[1].split('def ')[0]
            assert f'{flag}_req' in body, f'the {path} route is not gated by its own flag'
            assert 'infra_view_req' not in body, (
                f'{path} rides on the permission that only lets you look')
            assert f"wa._perm_required('{flag}')" in routes

    def test_marking_a_row_still_cannot_reach_a_machine_you_cannot_see(self):
        """Holding `infra_watch` is not being shown a machine. Every other route here narrows
        to what the caller may see, and a write must not be the one that forgets."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        body = routes.split("'/api/v1/infra/hosts/<uid>/watch'")[1].split('\n    @app.route')[0]
        assert '_may_see(' in body, 'the write does not narrow to what the caller may see'
        assert "wa._audit('infra_watch'" in body, (
            'nothing records who decided what the panel would report')

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
        # By its own path: the section has more than one POST, and "the first one" stopped
        # meaning the collection the day a second was added.
        body = routes.split("'/api/v1/infra/hosts/<uid>/collect'")[1].split('@app.route')[0]
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
        seconds and stay there for four minutes. What is being done is what makes that pause
        legible; a bar on its own reads as a hang."""
        src = self._collect()
        bar = src.split('function _infraCollectSlotHtml')[1].split(chr(10) + 'function ')[0]
        assert 'step.key' in bar and 'running.detail' in bar, (
            'the bar does not name what is working')
        assert '_infraCollectRow' in src, 'the dialog does not list what is being done'

    def test_a_timeout_is_not_drawn_as_a_failure(self):
        """The module has not failed — it is still working and writes its own state and
        history when it lands. A red cross is a thing the screen has to take back."""
        marks = self._collect().split('_INFRA_MARKS = {')[1].split('};')[0]
        assert "timeout: ['bi-hourglass-split',   'text-warning']" in marks, marks
        assert 'text-danger' not in marks.split('timeout:')[1]

    def test_one_map_decides_what_a_mark_means(self):
        """A module line and one of its own phases disagreeing about what a tick looks like
        is two vocabularies for one idea. Both states live in the same map — the executor's
        (pending/running/ok/error/timeout) and a phase's (run/done/fail) — because
        translating one into the other would be a third name for each."""
        marks = self._collect().split('_INFRA_MARKS = {')[1].split('};')[0]
        for key in ('pending', 'running', 'run', 'ok', 'done', 'error', 'fail', 'timeout'):
            assert f'{key}:' in marks, f'{key} has no mark and would draw as "waiting"'

    def test_it_is_a_checklist_and_not_a_list_of_module_ids(self):
        """Reported from the panel: a five-minute run showed `snmp · Ejecutando…` and nothing
        else, which is the same information as a spinner. Each line is a thing being done,
        with how far along it is where the module counts them."""
        row = self._collect().split('function _infraCollectRow')[1].split(chr(10) + 'function ')[0]
        assert 'm.steps' in row and '_infraChecklistLine' in row, (
            'the phases a module names for itself are not drawn')
        assert '<code' not in _strip_comments(row), (
            'a module still reads as an id in a code span')
        assert '_infraModuleLabel' in row, 'a module is named by its id and not by its name'
        line = self._collect().split('function _infraChecklistLine')[1].split(chr(10) + 'function ')[0]
        assert 'o.total' in line and 'progress-bar' in line, 'a phase cannot show its counter'

    def test_the_core_names_none_of_the_phases(self):
        """The words are the module's own — it is the only thing that knows what it is doing,
        and a vocabulary written here would fit whichever module was in front of whoever wrote
        it and be a lie for the other twenty."""
        row = self._collect().split('function _infraCollectRow')[1].split(chr(10) + 'function ')[0]
        for word in ('connect', 'Conect', 'read', 'Leyendo', 'sweep', 'analyse'):
            assert f"'{word}" not in row, f'the panel has invented a step name ({word})'

    def test_a_module_that_names_no_phase_still_says_something(self):
        """Most modules take a second and report no phases at all. Their line is the module,
        and the sentence they do send belongs on it — or it is a spinner with a name."""
        row = self._collect().split('function _infraCollectRow')[1].split(chr(10) + 'function ')[0]
        assert "!steps.length) ? (m.detail" in row

    def test_it_does_not_announce_an_ending_it_has_to_take_back(self):
        """Reported from the panel: a collection ended with a warning saying some modules were
        still working — a screen declaring itself finished over the top of a device still
        being walked. A module that overran keeps the run open (see `lib/core/infra/jobs.py`),
        so the dialog has a word for "waiting on it" that is not "finished"."""
        body = self._collect().split('function _infraCollectBody')[1].split(chr(10) + 'function ')[0]
        assert 'job.awaiting' in body and 'infra_collect_still_out' in body
        assert 'job.gave_up' in body and 'infra_collect_left_running' in body, (
            'no way to say the panel stopped waiting, which is the one case where '
            '"it carries on in the background" is true')

    def test_the_still_working_warning_only_fires_when_it_gave_up(self):
        """It used to fire on every collection of a NAS. It is a true sentence in exactly one
        case: the run was left going and nobody is watching it any more."""
        fin = self._collect().split('function _infraCollectFinish')[1].split(chr(10) + 'function ')[0]
        assert 'job.gave_up' in fin, 'the warning fires on a run that is still being waited for'

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


class TestACountIsAQuestion:
    """A tally answers "how is this switch" and immediately raises the next one.

    All of it in one box came out as "28 Ethernet 1 22 1 Loopback 21 Virtual (VLAN)" — a run
    of numbers and words with nothing between one pair and the next, where the eye has to work
    out which figure goes with which word, and a value the profile has no name for looks like a
    number whose label went missing. One card per value, and each of them opens onto its rows.
    """

    def test_each_counted_value_is_its_own_card(self):
        det = _read(os.path.join(INFRA, '_details.html'))
        assert 'function _infraTallyCard(' in det, 'the counts are drawn as one box again'
        assert '_infraTallyCard(m, v)' in det, 'the cards are not drawn per value'

    def test_every_card_opens_onto_the_rows_behind_it(self):
        det = _read(os.path.join(INFRA, '_details.html'))
        assert '_infraOpenTally(' in det, 'a count that cannot be opened is a dead end'
        # …and only when there is something to open. A chevron over an empty screen is a
        # promise the panel does not keep, so the click, the pointer and the arrow all hang
        # off the same count of what is behind the card.
        card = det.split('function _infraTallyCard(')[1].split('\nfunction ')[0]
        assert 'const behind = ((m.rows || {})[v] || []).length;' in card
        assert card.count('behind') >= 4, (
            'the card offers the click whether or not the payload carried the rows')

    def test_a_value_with_no_declared_word_still_reads_as_something(self):
        det = _read(os.path.join(INFRA, '_details.html'))
        assert 'infra_state_code' in det, 'an undeclared state prints as a bare number again'

    def test_a_count_opens_onto_a_screen_and_not_a_dialog(self):
        """The first answer was a table of every column the device reports, in the shared
        dialog. Reported from the screen: seventeen columns do not fit in one, and the
        horizontal scrollbar that was supposed to reach them sat at the bottom of forty rows.
        A port is not a row of a table anyway — it is a thing with a state, a speed, an address
        and four counters worth a graph each, which is a screen of its own."""
        det = _read(os.path.join(INFRA, '_details.html'))
        assert 'function _infraRowsPane(' in det
        assert 'function _infraTallyTable(' not in det, 'the table that did not fit is back'
        opener = det.split('function _infraOpenTally(')[1].split('\nfunction ')[0]
        assert 'showHtmlModal' not in opener, 'a count opens a dialog again'
        assert '_infraPaint()' in opener, 'and does not repaint what it opened'

    def test_the_rows_are_a_rail_and_the_one_you_pick_is_beside_it(self):
        det = _read(os.path.join(INFRA, '_details.html'))
        pane = det.split('function _infraRowsPane(')[1].split('\nfunction ')[0]
        for word in ('ss-rail-item', 'ss-sticky-aside', '_infraRowBody('):
            assert word in pane, f'{word} is not in the interfaces view'
        assert 'ss-scrollbox' in pane, (
            'a rail of sixty ports pushes what it selects off the bottom of the document')
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-scrollbox' in css, 'a class the markup uses and nothing defines'
        assert 'ss-widebody' not in css, 'a rule left behind by the table that is gone'

    def test_the_rows_come_from_the_payload_and_are_not_re_derived(self):
        """The filter that decides what a count is about lives on the server (`headline_rows`,
        `tally: "all"`, the state a reading maps to). A screen that re-applied it would be a
        second implementation, free to disagree — and the day it did, the switch would say
        "28 Ethernet" over a list of thirty."""
        det = _read(os.path.join(INFRA, '_details.html'))
        pane = det.split('function _infraRowsPane(')[1].split('\nfunction ')[0]
        assert '(m.rows || {})[_infraRowsOf.value]' in pane, 'the view picks its own rows'
        assert 'headline_rows' not in pane and 'tally_role' not in pane, (
            'the browser has started deciding which rows a count is about')
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        assert "bucket['rows'].setdefault" in svc, 'the server stopped saying which rows'

    def test_the_way_back_and_the_way_out(self):
        """A drill-down with no way back is a screen somebody reloads the page to leave. And it
        belongs to the device that was open: kept, the next machine's Details tab would open on
        a count of the previous one's ports."""
        det = _read(os.path.join(INFRA, '_details.html'))
        assert 'function _infraRowsBack(' in det and 'infra_rows_back' in det
        render = _read(os.path.join(INFRA, '_render.html'))
        opener = render.split('async function infraOpen(')[1].split('\n}')[0]
        assert '_infraRowsOf = null' in opener, 'the drill-down outlives the device'

    def test_a_view_change_asks_the_network_for_nothing(self):
        """Opening a count and picking a port are changes of VIEW. Through the section's entry
        point they would be two round trips and a blank pane to redraw what was already in
        memory."""
        render = _read(os.path.join(INFRA, '_render.html'))
        paint = render.split('function _infraPaint(')[1].split('\n}')[0]
        assert 'apiGet' not in paint and 'await' not in paint
        det = _read(os.path.join(INFRA, '_details.html'))
        for fn in ('_infraOpenTally', '_infraRowsBack', '_infraRowsPick'):
            body = det.split('function ' + fn + '(')[1].split('\nfunction ')[0]
            assert 'renderInfra()' not in body, f'{fn} refetches the fleet to change a view'

    def test_a_port_that_is_down_is_visible_without_opening_it(self):
        """Thirty ports on a rail, and the one that matters is the one that is down. The mark
        is the WORST of whatever the row's own columns declare a level for — the core is not
        deciding that an operational state outranks an administrative one."""
        det = _read(os.path.join(INFRA, '_details.html'))
        mark = det.split('function _infraRowMarkHtml(')[1].split('\nfunction ')[0]
        assert '_INFRA_LEVEL_MARKS' in mark, 'the rail invented its own symbols'
        assert 'oper' not in mark, (
            'the core has started naming the column that decides a port is down')
        assert 'r < worst.rank' in mark, 'the worst no longer wins'
        assert 'm.state_key || String(m.value)' in mark, (
            'the rail reads the raw value again, so a port that is down because somebody '
            'switched it off gets the same red octagon as a cable that fell out')
        assert 'st.icon ? 3 : -1' in mark, (
            'a state the profile gave a mark of its own no longer earns one — and "switched '
            'off" has no level, so the row goes back to having no mark at all')

    def test_a_coded_fact_is_named_by_the_profile_and_not_by_the_panel(self):
        """An interface's type arrives as "6". The profile already says 6 is Ethernet, in the
        states of the column that counts it — so the screen reads that map instead of carrying
        a second copy, which would be a second thing to keep up to date, and the panel naming
        a MIB's values on its own authority."""
        det = _read(os.path.join(INFRA, '_details.html'))
        fn = det.split('function _infraFactWord(')[1].split('\nfunction ')[0]
        assert 'st.label' in fn and 'value' in fn, 'a fact with no declared word is dropped'
        assert 'words.set(x.tally_role, x.states)' in det, (
            'the words no longer come from the column that counts them')
        assert 'Ethernet' not in _strip_comments(det), (
            'the panel has started writing down what a MIB means')


class TestTheMapIsReadAtAGlanceOrItIsNothing:
    """Reported from the screen: "no se ve la trazabilidad en absoluto".

    A lane per network and a line per membership, down the page — which on a router that
    declares twenty-nine routes came out as twenty-nine lanes, twenty-five of them with nobody
    in them, 3744 px tall, every line crossing the same ten-pixel channel to place five
    machines. Two rules replaced it: a network with nobody in it is not on the map, and
    membership is drawn by hanging off a plate rather than by a line across the picture.
    """

    def _js(self):
        return _read(os.path.join(INFRA, '_map.html'))

    def test_an_empty_network_is_not_a_branch(self):
        layout = _fn(self._js(), '_infraMapLayout')
        assert "(n.members || []).some(" in layout, (
            'every declared route is drawn again, whether anything lives there or not')

    def test_but_the_count_of_them_is_said(self):
        """Silently dropping them would be a map that knows something and does not say it."""
        js = self._js()
        assert 'function _infraMapFolded(' in js and 'infra_map_folded' in js

    def test_the_folded_count_is_the_networks_with_nobody_in_them(self):
        """Not "every network without a branch": a router's own network HAS a member, it is
        just drawn on the router. Counting it here puts a number under the picture that says
        something untrue about the fleet — which it did."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'filter(n => !(n.members || []).length).length' in layout
        assert 'length - nets.length' not in layout

    def test_a_machine_is_drawn_once(self):
        """Once per network would be four boxes with one name, and "which of these is the
        machine" is not a question a map should raise."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert '!home.has(uid)' in layout, 'a machine on three networks is drawn three times'

    def test_the_way_out_is_what_the_device_said_and_not_a_guess(self):
        """A machine another one points at, or one pointing at an address nobody here owns.
        Both are the device talking, which is what earns it the top of the picture."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert "e.kind === 'gateway' && e.to" in layout and "e.kind === 'exit'" in layout
        assert 'device_type' not in layout, (
            'the map has started deciding what a router is from the registry')

    def test_a_fleet_with_no_route_off_it_gets_no_cloud(self):
        cloud = _fn(self._js(), '_infraMapCloud')
        assert 'if (!L.exits.length) return' in cloud

    def test_the_lanes_are_gone(self):
        js = self._js()
        assert 'function _infraMapLane(' not in js, 'the lane layout is back'
        assert 'function _infraMapElbow(' in js, 'the short orthogonal links are gone'

    def test_the_kinds_of_line_are_still_told_apart(self):
        """Each is a different CLAIM — an address, a statement the device made, a cable it can
        see. Flattening them into "connected" would be the picture saying more than the data
        does, which is the one thing a map must not do."""
        links = _fn(self._js(), '_infraMapLinks')
        for kind in ("'lldp'", "'port'", "'gateway'"):
            assert kind in links, f'{kind} lines are no longer drawn as their own thing'
        assert 'stroke-dasharray="1 4"' in links, 'a port sighting reads as a cable again'
        legend = _fn(self._js(), '_infraMapLegend')
        assert legend.count('<svg') == 4, 'the legend stopped matching the lines'
