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

        This is not "the section is read-only" — it writes, and every one is deliberate:
        "collect now" runs this device's checks, which writes no record of its own and
        produces exactly what a scheduler cycle produces; "watch" sets one flag against one
        row; the map arrangement stores where the CALLER put the boxes, on their own account,
        exactly as the dashboard layout does. None of them stores a name, an address or a
        credential, and none can create or delete a machine. THAT is the property: an endpoint
        that edited the registry would be a second way into it from a screen deliberately
        handed to people who may not reach it.

        So every write is named here rather than tolerated, and each carries a flag of its
        own — checked below. Enumerated and not banned by verb: a verb ban reads as the
        property while only being a proxy for it, and the day a write is genuinely wanted the
        proxy is what gets edited.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        writes = set()
        for path, verbs in re.findall(r"@app\.route\('([^']+)',\s*methods=\[([^\]]+)\]\)",
                                      routes):
            for verb in re.findall(r"'(\w+)'", verbs):
                if verb != 'GET':
                    writes.add((verb, path))
        assert writes == {
            ('POST', '/api/v1/infra/collect'),
            ('POST', '/api/v1/infra/hosts/<uid>/collect'),
            ('POST', '/api/v1/infra/hosts/<uid>/watch'),
            ('PUT',  '/api/v1/infra/map-layout'),
        }, f'unexpected write route(s) in the infrastructure section: {sorted(writes)}'
        # The registry's own write path is what must not be reachable from here.
        for call in ('.create(', '.update(', '.delete('):
            assert f'store{call}' not in routes, (
                f'the section calls store{call} — that is the registry, behind its own '
                'permission, and this screen is not it')

    def test_and_the_only_account_field_it_writes_is_where_the_boxes_are(self):
        """It reaches the user record, which is a store with a permission of its own. What
        keeps that from being a way in is that it writes ONE key, on the caller's own record,
        holding coordinates — and the key is named here so a second one has to be argued for.
        """
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        touched = set(re.findall(r"user\[[\'\"](\w+)[\'\"]\]", routes))
        touched |= set(re.findall(r"user\.pop\([\'\"](\w+)[\'\"]", routes))
        assert touched <= {'infra_map_layouts'}, touched
        # …and it is the SESSION's user and never one named by the request.
        assert "wa._users.get(session.get('username', ''))" in routes

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
        # The bar itself, which is shared by both header slots — the device's and the fleet
        # list's. Two bars drawn from two copies would be two answers to "how far along".
        body = src.split('function _infraCollectBarHtml')[1].split(chr(10) + 'function ')[0]
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
        bar = src.split('function _infraCollectBarHtml')[1].split(chr(10) + 'function ')[0]
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
        """One vocabulary for "how is this machine": `ok/warning/error` and the empty string,
        which is what `hosts.service._host_statuses` produces. A second set of names would be
        a second definition of a broken host.

        And one BADGE for it, in the shared host vocabulary. It had its own, which is how the
        same host in maintenance came out orange with a cone on the fleet list and grey with a
        spanner here — reported from the screen. Two badges for one state is two states as far
        as anybody reading them can tell.
        """
        shared = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    'core', '_constants.html'))
        body = shared.split('const HOST_STATE_BADGES')[1].split('};')[0]
        for state in ('ok:', 'warning:', 'error:', 'maintenance:'):
            assert state in body, state
        # …and the two screens read it rather than each keeping one.
        for rel, fn in ((('infra', '_render.html'), '_infraStateBadge'),
                        (('servers', '_list.html'), '_srvStatusBadge')):
            src = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', *rel))
            own = src.split('function ' + fn)[1].split(chr(10) + '}')[0]
            assert 'hostStateBadge(' in own, fn
            assert 'text-bg-success' not in own, f'{fn} paints a state of its own again'
        render = _read(os.path.join(INFRA, '_render.html'))
        own = render.split('function _infraStateBadge')[1].split(chr(10) + '}')[0]
        assert 'infra_unwatched' in own, 'a host nobody watches has no state of its own'


class TestRefreshingTheWholeFleet:
    """The list's own button, beside the per-device one, and they are different acts.

    A device collection is narrowed to that device — quick, and it does not walk somebody
    else's rack. The list's is the un-narrowed run: every module with its whole configuration,
    which is what a scheduler cycle is and costs what one costs. Two buttons that look alike
    and cost differently need three things pinned: who may press it, that the screen says
    which of the two is running, and that it cannot be pressed while one is out.
    """

    def _collect(self) -> str:
        return _read(os.path.join(INFRA, '_collect.html'))

    def test_the_list_offers_it(self):
        src = _read(os.path.join(INFRA, '_list.html'))
        assert 'infraCollectAllSlot' in src and '_infraCollectAllSlotHtml()' in src

    def test_it_takes_both_flags_on_the_screen_and_in_the_route(self):
        """`infra_collect` says which ACT you may perform, not on which machines. A run over
        the whole fleet polls machines a narrowed operator may not be allowed to SEE, so the
        flag that says "you see the whole fleet" is what decides you may refresh it — and the
        screen and the route have to agree, or the button is offered and then refused."""
        src = _read(os.path.join(INFRA, '_list.html'))
        block = src.split('headerButtons')[1].split('refreshButton')[0]
        assert "has('infra_collect')" in block and "has('devices_view')" in block
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        body = routes.split('def api_infra_collect_all(')[1].split(chr(10) + '    @app.route')[0]
        assert "'devices_view' not in set(" in body, 'the route trusts the screen'

    def test_it_asks_first(self):
        """The per-device button does not, and should not: it is quick and it is about the
        machine you are looking at. This one costs a scheduler cycle and makes every check
        alert on what it finds, and the difference is invisible until it has started."""
        body = _fn(self._collect(), '_infraCollectAll')
        assert 'showConfirmModal(' in body
        assert 'infra_collect_all_confirm' in body

    def test_the_list_button_becomes_the_bar_for_ANY_run(self):
        """One collection runs at a time — the server holds the same lock the Status screen's
        run takes — so while a device is being collected this button cannot be pressed either.
        Leaving it as a button offers something that answers "already running"."""
        body = _fn(self._collect(), '_infraCollectAllSlotHtml')
        assert 'job.done' in body and 'job.host' not in body, (
            'it decides by whose run it is, so another run leaves it looking pressable')

    def test_both_slots_are_repainted(self):
        """Only one of the two is ever on screen, and painting only the device one is how the
        list's button sat there saying "collect" while a collection was running."""
        body = _fn(self._collect(), '_infraCollectPaint')
        assert "getElementById('infraCollectSlot')" in body
        assert "getElementById('infraCollectAllSlot')" in body

    def test_the_dialog_says_which_of_the_two_it_is(self):
        """The note under the bar is a claim about what is being polled. Fixed at "this device
        only" it is a lie for half the runs — and it is the only thing on the dialog that says
        which button started it."""
        body = _fn(self._collect(), '_infraCollectBody')
        assert 'infra_collect_this_device' in body and 'infra_collect_all_note' in body
        assert 'job.host' in body, 'it does not read the scope it is describing'

    def test_a_fleet_job_is_visible_to_whoever_sees_the_fleet(self):
        """Its job carries no host, and the two polling routes narrow by exactly that: with no
        host, `_may_see` is true only for `devices_view` — which is the same rule that let the
        run start. A job nobody can poll is a dialog that never updates."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'routes.py'))
        # Nested inside `register`, so read as text: what matters is the RULE, and the rule is
        # that with no uid only the fleet-wide flag can answer true.
        gate = routes.split('def _may_see(')[1].split('def ')[0]
        assert "'devices_view' in perms" in gate
        assert "f'server.{uid}.view' in perms" in gate


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
    """Reported from the screen twice, the second time with a picture: "eso es inusable".

    It is a TREE read downwards — what is outside, the way out, the networks, then what is on
    them — and that was right the first time. What was wrong was everything around it: thirty
    networks meant thirty columns, and the whole picture was then squashed into whatever width
    the pane happened to have, so the more the fleet had the smaller every name got.

    Three things fixed it and none of them is the shape: it is drawn on the shared canvas, so
    it is a WINDOW and wide is fine; the columns that were not worth one are gone; and the
    boxes can be dragged where the room actually is.

    The rules about what NOT to draw are each a claim:

    * a network nobody is on is a route, not a place — counted in a sentence;
    * a network with ONE machine on it is not a place where two machines meet — folded onto
      that machine (this is Docker's 172.17.0.0/16, which every container host has its own of);
    * a cable is a different question with a map of its own — not drawn twice.
    """

    def _js(self):
        return _read(os.path.join(INFRA, '_map.html'))

    def test_an_empty_network_is_not_a_branch(self):
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'if (!members.length) continue;' in layout, (
            'every declared route is drawn again, whether anything lives there or not')

    def test_a_network_of_one_is_folded_onto_the_machine_that_holds_it(self):
        """It is not a place where two machines meet, which is the only question this map
        exists to answer. Docker gives every host its own 172.17.0.0/16, and a router declares
        one per VLAN: on the reported screen those were most of the picture."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'members.length > 1 && !net.private' in layout
        assert 'solo.set(' in layout, 'they are dropped rather than folded'

    def test_and_a_private_range_is_not_shared_however_many_hold_it(self):
        """Two NAS both holding 172.17.0.1 are not neighbours: either it is not one network or
        one of them is unreachable, and in both cases joining them is a lie. The server flags
        it; this must not undo the flag by counting members."""
        assert '!net.private' in _fn(self._js(), '_infraMapLayout')

    def test_but_the_count_of_both_is_said(self):
        """Silently dropping them would be a map that knows something and does not say it."""
        js = self._js()
        assert 'function _infraMapFolded(' in js
        assert 'infra_map_folded' in js and 'infra_map_folded_solo' in js

    def test_the_folded_count_is_the_networks_with_nobody_in_them(self):
        """Not "every network without a column": a router's own network HAS a member, it is
        just drawn on the router. Counting it here puts a number under the picture that says
        something untrue about the fleet — which it did."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'filter(n => !(n.members || []).length).length' in layout

    def test_a_machine_is_drawn_once(self):
        """Once per network would be four boxes with one name, and "which of these is the
        machine" is not a question a map should raise. The others are a thin dashed line."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'if (!home.has(uid)) home.set(uid' in layout
        assert 'home.get(uid) === s.net' in layout

    def test_and_one_that_shares_no_network_is_still_on_the_picture(self):
        """It has an address and a state, and dropping it would be the map quietly deciding a
        machine does not exist because nothing else is on its subnet."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert 'orphans' in layout
        assert 'infra_map_no_shared' in self._js()

    def test_the_way_out_is_what_the_device_said_and_not_a_guess(self):
        """A machine another one points at, or one pointing at an address nobody here owns.
        Both are the device talking, which is what earns it the top of the picture."""
        layout = _fn(self._js(), '_infraMapLayout')
        assert "e.kind === 'gateway' && e.to" in layout and "e.kind === 'exit'" in layout
        assert 'device_type' not in layout, (
            'the map has started deciding what a router is from the registry')

    def test_a_fleet_with_no_route_off_it_gets_no_cloud(self):
        assert 'if (!L.exits.length) return' in _fn(self._js(), '_infraMapCloud')

    def test_the_wires_do_not_assume_a_box_is_where_it_was_generated(self):
        """They were orthogonal elbows — down, across, down — which is only readable while the
        thing below IS below. A dragged box makes that false, so they are curves."""
        wires = _fn(self._js(), '_infraMapWires')
        assert 'function _infraMapElbow(' not in self._js()
        assert 'const wire = (x1, y1, x2, y2, style)' in wires

    def test_the_cables_are_not_drawn_twice(self):
        """They have a map of their own now. Two pictures of one cable are two things to keep
        in agreement, and the reported screen had both on it — the crossing lines were half of
        why it could not be read."""
        wires = _fn(self._js(), '_infraMapWires')
        assert "'lldp'" not in wires and "'port'" not in wires
        js = self._js()
        assert "e.kind === 'lldp'" in js and "setInfraView('links')" in js

    def test_the_kinds_of_line_are_still_told_apart(self):
        """Each is a different CLAIM — an address, a statement the device made, a way off the
        fleet. Flattening them into "connected" would be the picture saying more than the data
        does, which is the one thing a map must not do."""
        legend = _fn(self._js(), '_infraMapLegend')
        assert legend.count('<svg') == 3, 'the legend stopped matching the lines'
        for key in ('infra_map_legend_net', 'infra_map_legend_gw', 'infra_map_legend_exit'):
            assert key in legend, key
            for lang in ('es_ES', 'en_EN'):
                assert f"'{key}'" in _read(os.path.join(
                    SRC, 'lib', 'i18n', 'lang', f'{lang}.py')), (key, lang)

    def test_it_is_a_window_and_not_a_picture_squashed_into_the_pane(self):
        """The whole complaint, in one property: the old one set `max-width` to its own width
        and let the browser shrink it, so the more the fleet had the smaller every name got."""
        js = self._js()
        assert 'ssCanvasAttrs(' in js and 'ss-mapfill' in js
        assert 'overflow-x:auto' not in js and 'max-width:' not in js


class TestTheRailReachesTheBottom:
    """Reported from the screen: on a device with sixty interfaces the rail stopped well
    short of the bottom of the window, with a band of empty page under it.

    Its ceiling was `calc(100vh - 13rem)` — a guess at everything above and below it, and on
    that page 208 px too many. What the rail can actually use is the height of the box it
    sticks inside, which is a number only the layout knows.
    """

    def _utils(self):
        return _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'core', '_utils.html')))

    def _tabs(self):
        return _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra', '_tabs.html')))

    def test_the_ceiling_is_measured_and_not_guessed(self):
        fn = _fn(self._utils(), 'capToScrollBox')
        assert 'clientHeight' in fn, 'it still works from a constant'
        assert 'closest(' in fn, 'nothing finds the box the list scrolls inside'

    def test_it_measures_the_BOX_and_not_where_the_rail_happens_to_be(self):
        """The rail moves: it starts under the section header and slides up until it sticks.
        An answer taken from where it is at render time is wrong at every other scroll
        position — which is the same class of mistake as the constant, with extra steps."""
        fn = _fn(self._utils(), 'capToScrollBox')
        assert 'getBoundingClientRect' not in fn, (
            'the cap is derived from the rail\'s current position')
        assert 'window.innerHeight' not in fn, 'back to measuring the window'

    def test_a_window_resized_is_measured_again(self):
        fn = _fn(self._utils(), 'capToScrollBox')
        assert "addEventListener('resize'" in fn
        assert 'isConnected' in fn and 'removeEventListener' in fn, (
            'a rail that has left the page keeps a listener alive for ever')

    def test_a_short_window_still_leaves_a_usable_rail(self):
        fn = _fn(self._utils(), 'capToScrollBox')
        assert 'Math.max(' in fn, 'a short window draws a rail two rows tall'

    def test_with_no_box_to_measure_the_stylesheet_keeps_its_ceiling(self):
        """A list drawn outside a scroll box still needs one, and no `max-height` at all is a
        rail as long as its list."""
        fn = _fn(self._utils(), 'capToScrollBox')
        assert 'if (!box) return;' in fn
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '.ss-scrollbox { overflow: auto; max-height:' in css, (
            'the fallback ceiling is gone — the jobs dialog uses it too')

    def test_the_rail_actually_asks_for_it(self):
        """The CALL and not the name: a function nobody calls is the trap this section has
        already fallen into once."""
        tabs = self._tabs()
        assert "capToScrollBox(document.getElementById('infra-rows-rail'))" in tabs, (
            'the ceiling is worked out by something the tab never calls')
        details = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra', '_details.html')))
        assert 'id="infra-rows-rail"' in details, 'the rail has no name to be found by'

    def test_it_is_asked_on_every_render_of_the_tab(self):
        """Picking a port rebuilds the rail, so a cap applied only on the first paint is a
        cap on an element that no longer exists."""
        tabs = self._tabs()
        block = tabs.split("tab === 'details'")[1].split('else if')[0]
        assert 'capToScrollBox(' in block, (
            'the cap is applied outside the branch that draws the rail')


class TestFlaggingARowShowsOnTheScreen:
    """Reported from the screen: pressing "watch" on a port left the rail without its bell
    and the button its old colour until F5 — and after F5 the flag was there, so the write
    had worked all along.

    `apiPost` answers `{status, data}`; the payload is one level down. Read as `r.watch` it
    was always `undefined`, so `r.watch || []` replaced the list with an EMPTY one on every
    click: the new flag never showed, and a flag already set on another row disappeared with
    it until the next load.
    """

    def _js(self):
        return _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra', '_details.html')))

    def test_it_reads_the_payload_where_the_payload_is(self):
        fn = _fn(self._js(), '_infraSetWatch')
        assert 'r.data' in fn, 'the answer is read one level too high'
        assert 'r.watch' not in fn.replace('r.data', ''), (
            'the response is still read as if apiPost returned the body')

    def test_a_reply_with_no_list_does_not_empty_the_one_on_screen(self):
        """The shape of the bug: `x || []` turns "I could not read it" into "there is
        nothing", which is a statement about the device rather than about the reply."""
        fn = _fn(self._js(), '_infraSetWatch')
        assert 'Array.isArray(' in fn, 'an unreadable answer still wipes the list'
        assert '|| []' not in fn, 'the empty-list fallback is back'

    def test_a_refusal_is_not_reported_as_a_success(self):
        """`infra_watch` is a permission of its own, so a refusal is a real answer here — and
        nothing was reading the status: a 403 toasted "watched" and left the screen claiming
        something that had not happened. The function's own docstring already promised this."""
        fn = _fn(self._js(), '_infraSetWatch')
        assert 'r.status >= 400' in fn
        assert "'danger'" in fn, 'a failure is announced as good news'

    def test_the_screen_is_repainted_from_what_came_back(self):
        """Not patched from what was clicked: what is on screen then IS what is stored."""
        fn = _fn(self._js(), '_infraSetWatch')
        assert '_infraWatchPaint(' in fn
        assert fn.index('_infraDetail.host.watch') < fn.index('_infraWatchPaint('), (
            'it repaints before it has the new list')

    def test_it_repaints_the_flag_and_not_the_device(self):
        """Reported from the screen: flagging a port reloaded every chart on it. It went
        through `_infraPaint`, which rewrites the device's whole markup — and a chart is a
        request to the history API and a canvas drawn from the answer, so moving one icon
        threw away a week of traffic per picture and blinked them back in as they arrived.

        Nothing else on screen depends on the flag: it turns a profile's verdict back on for
        that row, which is the SAMPLER's business on the next collection."""
        fn = _fn(self._js(), '_infraSetWatch')
        assert '_infraPaint()' not in fn, (
            'the whole device is rebuilt to move one bell')
        paint = _fn(self._js(), '_infraWatchPaint')
        assert 'data-watch-bell' in paint and "getElementById('infra-watch-btn')" in paint, (
            'it does not reach the two things the flag decides')
        assert 'innerHTML = _infraHostHtml' not in paint

    def test_only_the_row_that_changed_changes(self):
        """The rail carries one slot per row; a flag on one of them must not touch the
        others, and the body may be showing a different port entirely."""
        paint = _fn(self._js(), '_infraWatchPaint')
        assert 'el.dataset.watchBell === row' in paint, (
            'every bell on the rail is rewritten, whichever row was flagged')
        assert "btn.dataset.row !== row" in paint, (
            'the button is repainted for a row it is not showing')

    def test_a_live_button_gets_a_function_and_not_an_attribute(self):
        """`jsStr` HTML-ESCAPES what it quotes — everywhere else it is written into markup,
        and the parser undoes that when it compiles the handler. `setAttribute` sets the value
        literally, so the handler read `_infraSetWatch(&quot;snmp&quot;,...)`: a syntax error,
        and the button stopped responding until something re-rendered it through the HTML
        path. Reported from the screen exactly that way — flag a port, then nothing happens
        until you switch ports and come back.

        Patching a live element has no markup in it, so it needs no quoting."""
        paint = _fn(self._js(), '_infraWatchPaint')
        assert 'btn.onclick =' in paint, 'the handler is installed as a string again'
        assert "setAttribute('onclick'" not in paint
        assert 'jsStr(' not in paint, (
            'a value is being quoted for markup while patching a live element')

    def test_the_two_fragments_are_written_once(self):
        """Both are drawn twice — when the pane is built and again when the flag changes — and
        a second copy of a fragment is a second thing to keep in step."""
        js = self._js()
        assert 'function _infraWatchBell(' in js and 'function _infraWatchBtnInner(' in js
        # Twice in the whole file: once in each helper, and nowhere else.
        assert js.count('bi-bell-fill') == 2, (
            'the bell markup is spelt out somewhere instead of being asked for')
        for fn in ('_infraWatchBell', '_infraWatchBtnInner'):
            assert 'bi-bell-fill' in _fn(js, fn), f'{fn} no longer draws it'


class TestTheIdentityColumnDoesNotRepeatTheHeader:
    """The registry's own record used to lead that column — address, type, how it is reached,
    OS, description. Every one is already on the page or one click from it: the header above
    carries the name, the address, the state and the tags, and the rest is the registry's,
    behind the button that opens it. A card that repeats the line above it costs a screenful
    and answers nothing new."""

    def _tabs(self):
        return _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra', '_tabs.html')))

    def test_the_record_card_is_gone(self):
        fn = _fn(self._tabs(), '_infraIdentityHtml')
        assert 'infra_record' not in fn
        assert 'host_address' not in fn, 'the address is repeated under the header again'

    def test_and_so_is_the_word_it_used(self):
        for lang in ('es_ES', 'en_EN'):
            src = _read(os.path.join(SRC, 'lib', 'i18n', 'lang', lang + '.py'))
            assert "'infra_record'" not in src, f'{lang} keeps a label nothing draws'

    def test_what_the_device_says_about_itself_stays(self):
        """That is the half nothing else on the page shows."""
        fn = _fn(self._tabs(), '_infraIdentityHtml')
        assert 'groups.values()' in fn and 'g.facts' in fn

    def test_a_device_that_says_nothing_still_says_so(self):
        """The empty state used to be reached only when the registry card was empty too."""
        fn = _fn(self._tabs(), '_infraIdentityHtml')
        assert 'infra_no_identity' in fn
        assert '!reg.length' not in fn, (
            'the empty state is still gated on a card that no longer exists')

    def test_the_header_is_where_those_facts_are(self):
        """Removing a card is only right while the thing it said is somewhere else."""
        render = _strip_comments(_read(os.path.join(
            SRC, 'lib', 'web_admin', 'templates', 'partials', 'infra', '_render.html')))
        head = _fn(render, '_infraHostHtml')
        assert 'h.address' in head and 'h.name' in head, (
            'the device header no longer carries what the record card used to')


class TestAFactThatIsAListOfRows:
    """"Which ports are in that LAG" is answered, and then somebody wants to open one.

    Reported from the screen: the members were there and were words. A fact whose value happens
    to be several row names is a fact somebody wants to press.

    The screen does NOT split the words to find out which rows they are — a row name may
    contain the separator, and the side that built the list already knows. So the list travels
    as a list beside the words it reads as.
    """

    def _det(self):
        return _read(os.path.join(INFRA, '_details.html'))

    def test_the_server_says_which_rows_the_list_is(self):
        svc = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'service.py'))
        body = svc.split('def _aggregate_members(')[1].split(chr(10) + 'def ')[0]
        assert "'rows': listed" in body, 'the screen is left to split a string on a comma'

    def test_and_the_screen_makes_each_one_a_way_in(self):
        body = _fn(self._det(), '_infraRowFactsHtml')
        assert '(a.rows || []).length' in body
        assert 'infraGoRow(' in body

    def test_landing_on_a_row_is_the_same_code_as_arriving_from_the_map(self):
        """"Find the row called this and show it" is one behaviour, and a second implementation
        would be free to disagree about which row `ether11` is."""
        body = _fn(self._det(), 'infraGoRow')
        assert '_infraPortWanted' in body and '_infraFocusPort()' in body


class TestOneStateLooksLikeOneState:
    """A machine's state has a colour, and it had four.

    The badge, the stripe down a card, the dot beside a board column and the box on a map each
    worked it out for themselves — so a host in maintenance came out orange on the fleet list,
    grey in the infrastructure badge, and grey again on the board. Reported from the screen
    twice: once for the badge, and once more for the cards after the badge was fixed, which is
    exactly what happens when a duplicate is fixed one copy at a time.
    """

    CORE = os.path.join(TPL, 'partials', 'core', '_constants.html')

    def test_there_is_one_palette(self):
        core = _read(self.CORE)
        assert 'const HOST_STATE_COLORS' in core and 'function hostStateColor(' in core
        block = core.split('const HOST_STATE_COLORS')[1].split('};')[0]
        for state in ('maintenance:', 'error:', 'warning:', 'ok:'):
            assert state in block, state

    def test_and_maintenance_is_the_orange_it_has_always_been(self):
        """Deliberately not the yellow of a warning: "somebody switched this off on purpose"
        and "something is wrong with it" are not the same news."""
        block = _read(self.CORE).split('const HOST_STATE_COLORS')[1].split('};')[0]
        assert '#fd7e14' in block

    def test_nothing_in_the_section_paints_a_state_itself(self):
        """The rule that stops this coming back one screen at a time.

        A colour beside the word `status` is a screen deciding what a state looks like. The
        cable map's own `_LNK_STROKE` is not one of those: how sure the picture is about a
        CABLE is a different vocabulary with different words in it, and it is not about a
        machine at all.
        """
        for name in ('_list.html', '_group_views.html', '_links.html', '_map.html',
                     '_render.html'):
            src = _strip_comments(_read(os.path.join(INFRA, name)))
            assert '#fd7e14' not in src, f'{name} paints maintenance itself'
            for line in src.splitlines():
                if 'status' in line and ('bs-danger' in line or 'bs-success' in line):
                    raise AssertionError(f'{name} decides what a state looks like: {line!r}')

    def test_the_map_boxes_read_it_too(self):
        for name, fn in (('_links.html', '_infraLinkBox'), ('_map.html', '_infraMapBox')):
            body = _read(os.path.join(INFRA, name)).split(
                'function ' + fn + '(')[1].split(chr(10) + '}')[0]
            assert 'hostStateColor(' in body, name


class TestTheReloadDoesNotFlashWhite:
    """Reported from the screen: every refresh paints white before the page arrives.

    It is not the page's white — it is the browser's own canvas, in the moment BEFORE any
    stylesheet has been fetched and parsed. Which is why the answer cannot live in a
    stylesheet: anything there is by definition too late.
    """

    def _base(self):
        return _read(os.path.join(TPL, 'base.html'))

    def test_the_canvas_is_told_which_scheme_it_is(self):
        """`color-scheme` is what makes the default background, the scrollbars and the form
        controls dark before a rule of ours is parsed."""
        assert '<meta name="color-scheme"' in self._base()

    def test_and_the_colour_is_said_before_any_stylesheet(self):
        base = self._base()
        style = base.index('<style>html{background:')
        # The LINK and not the word: the note above the rule names the stylesheet it
        # duplicates a colour out of, which is the sentence a search for the word finds.
        for sheet in ('/static/css/bootstrap.min.css', '/static/css/web_admin.css'):
            assert style < base.index(f'href="{sheet}'), f'the paint comes after {sheet}'

    def test_it_is_the_same_flag_the_document_uses(self):
        """No moment where the document knows the theme and the paint does not."""
        base = self._base()
        assert base.count("{{ 'dark' if dark_mode else 'light' }}") >= 2
        assert "{{ '#181818' if dark_mode else '#f5f6fa' }}" in base

    def test_and_it_is_the_colour_the_stylesheet_settles_on(self):
        """The one colour duplicated out of the stylesheet, so it is pinned to it here."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert '--bs-body-bg:                   #181818;' in css
        assert '[data-bs-theme="light"] body { background-color: #f5f6fa }' in css

    def test_and_nothing_is_shown_before_it_is_dressed(self):
        """A `<link>` in the head is render-blocking in theory. In practice a browser paints
        the document bare once its own paint-suppression window runs out, which on a slow link
        is a screenful of serif text and bullet lists — reported from the screen, with a
        picture of it, showing the boot splash undressed.

        Held by the LAST stylesheet, which is the one that means "dressed", and released by a
        timeout as well: a stylesheet that 404s would otherwise leave a blank page for ever,
        and the worst case has to stay the bare document — which is what happens today.
        """
        base = self._base()
        assert 'class="ss-nocss"' in base
        assert 'html.ss-nocss body{visibility:hidden}' in base
        assert "classList.remove('ss-nocss')" in base, 'a broken stylesheet is a blank page'
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        assert 'html.ss-nocss body { visibility: visible; }' in css

    def test_and_the_stylesheets_are_cached_instead_of_revalidated(self):
        """Half a megabyte of CSS costs a round trip each before anything is drawn, and that
        wait is the whole reason the browser gives up. A versioned URL cannot go stale — a new
        build is a new URL — so it may be kept for a year; the fonts a stylesheet pulls in
        under a name of its own may not, because nothing can bust them."""
        base = self._base()
        for asset in ('bootstrap.min.css', 'bootstrap-icons.min.css', 'bootstrap.bundle.min.js'):
            assert f'{asset}?v={{{{ asset_v }}}}' in base, asset
        hooks = _read(os.path.join(SRC, 'lib', 'web_admin', 'mixins', 'hooks.py'))
        body = hooks.split('def _hook_trace_end(')[1].split(chr(10) + '    def ')[0]
        assert "request.args.get('v')" in body
        assert 'max-age=31536000, immutable' in body and 'max-age=86400' in body


class TestAMakersMarkFitsItsBox:
    """A brand mark is drawn by its HEIGHT and left to work out its own width.

    Which only works while each file's ``viewBox`` is the ink it holds. Upstream draws every
    mark inside a 24x24 canvas, so a WORDMARK — Synology, HP — fills the width and leaves two
    thirds of the height empty; fitted into a box that way it came out a third of the height of
    the text beside it. Reported from the screen.

    Silent, which is why this is a test: a logo drawn small looks like somebody's decision.
    """

    DIR = os.path.join(SRC, 'lib', 'web_admin', 'static', 'img', 'brands')
    NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?')
    CMD = re.compile(r'([MmZzLlHhVvCcSsQqTtAa])([^MmZzLlHhVvCcSsQqTtAa]*)')
    #: How many numbers each command takes. An arc's first five are radii and flags, not a
    #: point — reading them as coordinates would put the box where the drawing never goes.
    ARGS = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}

    def _ink(self, d):
        """The box the path visits: on-curve points plus control points, which is a superset
        of the true outline by at most part of a curve's bulge."""
        x = y = 0.0
        start = (0.0, 0.0)
        pts = []
        for letter, rest in self.CMD.findall(d):
            up, rel = letter.upper(), letter.islower()
            nums = [float(n) for n in self.NUM.findall(rest)]
            take = self.ARGS[up]
            if take == 0:
                x, y = start
                pts.append((x, y))
                continue
            for i in range(0, len(nums) - take + 1, take):
                arg = nums[i:i + take]
                if up == 'H':
                    x = x + arg[0] if rel else arg[0]
                elif up == 'V':
                    y = y + arg[0] if rel else arg[0]
                elif up == 'A':
                    x, y = (x + arg[5], y + arg[6]) if rel else (arg[5], arg[6])
                else:
                    base = (x, y)
                    for j in range(0, take, 2):
                        px, py = arg[j], arg[j + 1]
                        if rel:
                            px, py = base[0] + px, base[1] + py
                        pts.append((px, py))
                        x, y = px, py
                pts.append((x, y))
                if up == 'M' and i == 0:
                    start = (x, y)
        xs, ys = zip(*pts)
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def _marks(self):
        return sorted(f for f in os.listdir(self.DIR) if f.endswith('.svg'))

    def test_there_are_marks_to_draw(self):
        assert len(self._marks()) >= 4

    def test_every_marks_box_is_the_ink_it_holds(self):
        """Within a tenth: the box is a superset, so a little slack is the method and not a
        mistake. A wordmark left in the 24x24 canvas is off by a factor of four."""
        loose = []
        for name in self._marks():
            src = _read(os.path.join(self.DIR, name))
            box = [float(v) for v in re.search(r'viewBox="([^"]+)"', src).group(1).split()]
            ink = self._ink(re.search(r'\sd="([^"]+)"', src).group(1))
            for i, (declared, actual) in enumerate(zip(box[2:], ink[2:])):
                if declared > actual * 1.1 + 0.05:
                    loose.append((name, 'wh'[i], declared, actual))
        assert not loose, f'boxes bigger than their ink (drawn small): {loose}'

    def test_a_mark_takes_the_theme_and_never_paints_over_it(self):
        """The files are black silhouettes with no colour of their own, which is right on a
        light panel and invisible on a dark one."""
        css = _read(os.path.join(SRC, 'lib', 'web_admin', 'static', 'css', 'web_admin.css'))
        rule = css.split('.ss-brand {')[1].split('}')[0]
        assert 'width: auto' in rule, 'a fixed width is a squashed wordmark'
        assert '[data-bs-theme="dark"] .ss-brand { filter: invert(1); }' in css
        for name in self._marks():
            src = _read(os.path.join(self.DIR, name))
            assert 'fill=' not in src, f'{name} paints itself and will not take the theme'

    def test_and_where_the_mark_is_drawn_the_name_is_not(self):
        """A logo is the maker's name written by the maker: "[Synology] Synology" is the same
        word twice, and it was on every card of a machine whose mark we happen to ship."""
        src = _strip_comments(_read(os.path.join(TPL, 'partials', 'core', '_constants.html')))
        body = _fn(src, 'hostBrandHtml')
        assert 'hostBrandMarkHtml' in body and 'if (mark) return mark;' in body
        card = _strip_comments(_read(os.path.join(INFRA, '_tabs.html')))
        head = card.split('const block = (title')[1].split('const facts')[0]
        assert 'hostBrandMarkHtml(brand' in head, 'the card draws no mark'
        assert 'title === (brand || {}).name' in head, 'the card writes the maker out twice'
