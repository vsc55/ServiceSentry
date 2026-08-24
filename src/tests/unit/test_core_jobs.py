#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background jobs — the screen that says what the panel is doing when nobody is watching.

A collection polling forty machines, a copy of the database, a MIB tree compiling, a profile
being tested: four pieces of work in four background threads, each keeping its own dict of
jobs in its own module, each visible only from the page that started it. Navigate away and the
work carried on with nowhere to look at it, and "why is the panel slow" had no answer anybody
could reach.

What this file pins is the two properties that make the collector generic — the core names
nobody, and one package answering rubbish must not take the list down — and the one that makes
it safe: it starts nothing.
"""

import os
import re

from tests.helpers import _fn, _read

from lib.core.jobs import record as jobs_record
from lib.core.jobs import service as jobs_svc
from lib.core.jobs.history import JobHistoryStore
from lib.db import get_connector
from lib.discovery import scan

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


class TestThePackagesDeclareAndTheCoreCollects:

    def test_the_core_names_nobody(self):
        """A core that imported four job registries by name would have to be edited to learn
        about a fifth. Same discovery permissions, overview widgets and notify events use."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'service.py'))
        assert 'scan(DESCRIPTOR)' in src
        body = src.split('def live')[1]
        for name in ('infra', 'backup', 'snmp', '_JOBS', '_compile_jobs'):
            assert f"'{name}'" not in body, f'the collector has started naming {name}'

    def test_the_packages_that_run_work_declare_it(self):
        declared = {name for name, _v in scan(jobs_svc.DESCRIPTOR)}
        assert {'infra', 'backup', 'snmp'} <= declared, (
            f'a package that runs background work stopped declaring it: {sorted(declared)}')

    def test_every_declaration_is_callable_and_answers_a_list(self):
        for name, descriptor in scan(jobs_svc.DESCRIPTOR):
            assert callable(descriptor), f'{name} declared something that is not a function'
            assert isinstance(descriptor(None), list), f'{name} did not answer a list'

    def test_the_screen_that_lists_them_does_not_list_itself(self):
        declared = {name for name, _v in scan(jobs_svc.DESCRIPTOR)}
        assert 'jobs' not in declared, 'the jobs list would always have one row: itself'


class TestOneBrokenPackageIsNotAnEmptyScreen:

    def test_a_package_that_raises_is_skipped(self):
        """Three of the four is worth more than nothing because a fourth thing is broken."""
        def _boom(_wa):
            raise RuntimeError('this package is having a bad day')

        real = jobs_svc.scan
        jobs_svc.scan = lambda _c: [('boom', _boom),
                                    ('fine', lambda _wa: [{'id': 'x', 'kind': 'k'}])]
        try:
            got = jobs_svc.live(None)
        finally:
            jobs_svc.scan = real
        assert [j['source'] for j in got] == ['fine']

    def test_a_package_answering_rubbish_produces_a_row_and_not_a_crash(self):
        job = jobs_svc.normalise('x', {'total': '?', 'done': -4, 'state': 'weird',
                                       'started': 'yesterday'})
        assert job['total'] == 0 and job['done'] == 0
        assert job['state'] == 'running', 'an unknown state is drawn as something'
        assert job['started'] == 0.0

    def test_a_count_past_its_total_is_clamped(self):
        """What a scope narrowed halfway through looks like: "compiling 28 of 3", and a
        progress bar at 933 % — which is exactly what the MIB screen once showed."""
        assert jobs_svc.normalise('x', {'done': 28, 'total': 3})['done'] == 3

    def test_a_job_that_never_said_how_many_gets_no_bar(self):
        """Zero is "no idea how many", not a bar sitting at 0 %."""
        assert jobs_svc.normalise('x', {'done': 5})['total'] == 0

    def test_a_field_nobody_filled_in_is_a_blank_and_not_a_missing_key(self):
        job = jobs_svc.normalise('x', {})
        assert set(job) == {'id', 'source', 'kind', 'label', 'detail', 'state', 'started',
                            'done', 'total', 'error', 'steps'}
        assert job['steps'] == [], 'a job that reports no steps has an empty list, not None'
        assert job['source'] == 'x'


class TestTheOrderIsWhatSomebodyOpensItFor:

    JOBS = [{'id': '1', 'state': 'done', 'started': 900},
            {'id': '2', 'state': 'running', 'started': 100},
            {'id': '3', 'state': 'failed', 'started': 500},
            {'id': '4', 'state': 'running', 'started': 800}]

    def test_running_first_then_newest(self):
        got = [j['id'] for j in jobs_svc.ordered(self.JOBS)]
        assert got == ['4', '2', '3', '1'], (
            'a finished job sits above work that is still going on: ' + ','.join(got))

    def test_the_summary_and_the_list_cannot_disagree(self):
        assert jobs_svc.summary(self.JOBS) == {'running': 2, 'done': 1, 'failed': 1,
                                               'interrupted': 0, 'total': 4}

    def test_a_run_that_did_not_come_back_sorts_between_the_two(self):
        """It is not a success and not a fault: the panel stopped while it was working."""
        order = [j['state'] for j in jobs_svc.ordered(
            [{'state': x, 'started': 0} for x in
             ('done', 'interrupted', 'failed', 'running')])]
        assert order == ['running', 'failed', 'interrupted', 'done']

    def test_a_job_that_never_started_has_no_age(self):
        assert jobs_svc.age({'started': 0}) == 0.0
        assert jobs_svc.age({'started': 100}, now=160) == 60.0


class TestItStartsNothing:

    def test_the_route_is_a_get_and_only_a_get(self):
        """Every row is work another permission already let somebody begin, and the buttons
        that begin it live on the screens that own it. A control here would be a second way
        into four pieces of machinery from one place that understands none of them."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'routes.py'))
        assert not re.search(r"methods=\['(POST|PUT|DELETE|PATCH)'\]", routes)
        assert "wa._perm_required('jobs_view')" in routes

    def test_looking_is_granted_to_whoever_may_look(self):
        """It starts nothing, cancels nothing and shows no credential. "Why is this slow" and
        "did my backup finish" are questions somebody watching a wall screen has as much right
        to as anybody."""
        manifest = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'manifest.py'))
        m = re.search(r"\{'flag': 'jobs_view',\s*'roles':\s*\(([^)]*)\)", manifest)
        assert m, 'jobs_view is not declared in the domain manifest'
        roles = {r.strip().strip("'\"") for r in m.group(1).split(',') if r.strip()}
        assert 'viewer' in roles

    def test_the_clock_travels_with_the_answer(self):
        """"Running for 4 minutes" is arithmetic on two clocks otherwise, and a laptop a
        minute out would show a job that started in the future."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'routes.py'))
        assert "'now': time.time()" in routes
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                '_render.html'))
        assert '(now || j.started) - j.started' in js, 'the browser times it with its own clock'

    def test_it_polls_faster_while_something_is_running(self):
        """A progress bar that moves once a minute reads as one that has hung; an empty list
        has nothing to be fresh about."""
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                '_render.html'))
        assert '_JOBS_TICK' in js and 'busy:' in js and 'idle:' in js
        assert "classList.contains('active')" in js, (
            'it keeps polling a pane nobody is looking at')

    def test_the_section_is_wired_end_to_end(self):
        """One registry entry is what gives a section its URL, its route, its permission gate
        and its menu item — and the pane and the bundle are the two halves that fail
        silently: miss the pane and it opens onto nothing, miss the include and the menu
        offers a section whose renderer is not defined."""
        consts = _read(os.path.join(SRC, 'lib', 'web_admin', 'constants.py'))
        for want in ("'id': 'jobs'", "'render': 'renderJobs'", "'perm': 'jobs_view'",
                     "'pane': 'tab-jobs'"):
            assert want in consts, f'{want} is not in the page registry'
        dash = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'dashboard.html'))
        assert 'partials/jobs/_pane.html' in dash
        pane = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                  '_pane.html'))
        assert 'id="tab-jobs"' in pane and 'id="jobs-container"' in pane
        bundle = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                                    '_js_sections.html'))
        assert 'partials/jobs/_render.html' in bundle
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                '_render.html'))
        assert 'function renderJobs(' in js, 'the registry names a renderer that is not there'
        index = _read(os.path.join(SRC, 'lib', 'web_admin', 'routes', '__init__.py'))
        assert '_jobs(app, wa)' in index


class TestOpeningARunningJob:
    """A row gets one line, which answers "is it going" and not "what is it doing" — and on a
    collection that has been running four minutes those are different questions."""

    def _js(self):
        return _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                  '_render.html'))

    def test_the_row_is_the_way_in(self):
        js = self._js()
        assert '_jobsOpenLive(' in js and 'ss-pointer' in js

    def test_the_dialog_keeps_up_with_the_job(self):
        """Opening one and watching it stop moving is the same complaint the whole screen
        exists to answer, one level down."""
        js = self._js()
        assert '_jobsWatching' in js
        paint = _fn(js, '_jobsPaint')
        assert '_jobsShowLive(_jobsWatching)' in paint

    def test_a_job_that_ends_while_it_is_open_does_not_shut_the_dialog(self):
        """Closing it would be the screen taking the answer away at the moment it arrived."""
        show = _fn(self._js(), '_jobsShowLive')
        assert "_jobsWatching = ''" in show and 'return' in show
        assert 'hideInfoModal' not in show

    def test_the_screen_colours_four_words_and_no_others(self):
        """A package reporting a fifth gets a line with no mark rather than a wrong one."""
        js = self._js()
        block = js.split('_JOBS_STEP = {')[1].split('};')[0]
        for state in ('pending', 'running', 'ok', 'failed'):
            assert f'{state}:' in block, f'{state} lost its mark'
        assert "'':" in block, 'a state this screen has not heard of has nothing to draw'
        assert set(jobs_svc.STEP_STATES) == {'pending', 'running', 'ok', 'failed'}

    def test_a_package_step_vocabulary_does_not_travel(self):
        """A screen cannot colour a word it has never heard of, so a package's own state names
        are translated where they are produced and anything unrecognised arrives blank."""
        got = jobs_svc.normalise('x', {'steps': [{'state': 'gone_fishing', 'text': 'a'}]})
        assert got['steps'][0]['state'] == '', 'a word this screen cannot colour got through'
        src = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'jobs.py'))
        assert '_LIVE_STATE = {' in src, 'the module stopped translating its own words'

    def test_a_module_that_overran_is_still_running(self):
        """Reported from the screen: a switch's collection showed the SNMP module in RED on
        the jobs list while the collection dialog, at that same moment, said "still working" —
        and the collection dialog was right. `timeout` means the batch's deadline passed; the
        module did not stop, and nothing can stop it. Counting it as finished also put the bar
        at 1/1 under the word "running"."""
        import lib.core.infra.jobs as infra_jobs             # noqa: PLC0415
        real = dict(infra_jobs._JOBS)
        infra_jobs._JOBS.clear()
        infra_jobs._JOBS['j'] = {
            'id': 'j', 'host_name': 'SW', 'done': False, 'error': '', '_started': 1.0,
            'modules': [{'module': 'snmp', 'label': 'SNMP', 'state': 'timeout',
                         'steps': [{'key': 'reading', 'scope': 'sw', 'state': 'run'}]}]}
        try:
            job = infra_jobs.live(None)[0]
        finally:
            infra_jobs._JOBS.clear()
            infra_jobs._JOBS.update(real)
        assert job['state'] == 'running'
        assert (job['done'], job['total']) == (0, 1), 'the bar says it finished'
        assert [s['state'] for s in job['steps']] == ['running', 'running'], (
            'a module that overran is drawn as failed, and its steps stop being shown')

    def test_a_step_with_no_text_is_not_a_step(self):
        assert jobs_svc.normalise('x', {'steps': ['', '   ', {'text': ''}]})['steps'] == []

    def test_a_step_keeps_its_columns(self):
        """Flattened to one sentence it read "erebor · Reading the metrics · 2/24 Disks" —
        the same words with the thing that makes forty of them scannable taken away."""
        got = jobs_svc.normalise('x', {'steps': [
            {'state': 'running', 'text': 'Reading', 'scope': 'erebor',
             'n': 2, 'total': 24, 'note': 'Disks'}]})['steps'][0]
        assert got['scope'] == 'erebor' and got['note'] == 'Disks'
        assert (got['n'], got['total']) == (2, 24)

    def test_a_counter_with_nothing_to_compare_it_to_is_not_a_counter(self):
        """A total of zero is a package saying it does not know how many."""
        got = jobs_svc.normalise('x', {'steps': [{'text': 'a', 'n': 7, 'total': 0}]})['steps'][0]
        assert 'n' not in got and 'total' not in got

    def test_a_count_past_its_own_total_is_clamped_too(self):
        got = jobs_svc.normalise('x', {'steps': [{'text': 'a', 'n': 99, 'total': 8}]})['steps'][0]
        assert got['n'] == 8

    def test_a_bare_string_is_still_a_step(self):
        got = jobs_svc.normalise('x', {'steps': ['just a line']})['steps'][0]
        assert got['text'] == 'just a line' and got['scope'] == '' and got['sub'] is False

    def test_the_collection_hands_over_the_lines_its_own_dialog_draws(self):
        """The jobs dialog showed "0 / 1  0 %" and one red word while the collection dialog, at
        that moment, was listing five machines and what each of them was reading."""
        import lib.core.infra.jobs as infra_jobs             # noqa: PLC0415
        real = dict(infra_jobs._JOBS)
        infra_jobs._JOBS.clear()
        infra_jobs._JOBS['j'] = {
            'id': 'j', 'host_name': 'SW', 'done': False, 'error': '', '_started': 1.0,
            'modules': [{'module': 'snmp', 'label': 'SNMP', 'state': 'running', 'detail': '',
                         'steps': [{'key': 'Reading', 'scope': 'erebor', 'state': 'run',
                                    'n': 2, 'total': 24, 'note': 'Disks'}]}]}
        try:
            steps = jobs_svc.live(None)[0]['steps']
        finally:
            infra_jobs._JOBS.clear()
            infra_jobs._JOBS.update(real)
        assert steps[0]['text'] == 'SNMP' and not steps[0].get('sub')
        assert steps[1] == {'state': 'running', 'text': 'Reading', 'scope': 'erebor',
                            'note': 'Disks', 'n': 2, 'total': 24, 'sub': True}, (
            'a step lost a column between the package and the screen')


class TestWhoWasRunningIt:
    """`owner` is the panel's own identity — `host:pid:role`, the same name the heartbeat
    writes into the service registry and the health screen shows. A fresh uuid would have been
    unique and meant nothing anywhere else."""

    def test_the_owner_is_a_name_somebody_can_look_up(self):
        assert jobs_record._identity('').count(':') >= 1, (
            'the owner stopped being host:pid:role')
        assert jobs_record._identity('erebor:9:web') == 'erebor:9:web', (
            'a caller that knows who it is was overruled')

    def test_it_is_new_on_every_start(self):
        """Which is the property the sweep needs: no row at start-up can be this run's."""
        import os                                            # noqa: PLC0415
        assert str(os.getpid()) in jobs_record._identity('')

    def test_the_row_remembers_it(self):
        st = _hist()
        uid = st.begin(_job(), owner='erebor:4120:web')
        assert st.get(uid)['owner'] == 'erebor:4120:web'

    def test_a_panel_that_is_up_keeps_its_job(self):
        """Two panels sharing a database must not declare each other's work dead: one of them
        starting would close a job the other is running."""
        st = _hist()
        mine = st.begin(_job(id='mine'), owner='erebor:1:web')
        theirs = st.begin(_job(id='theirs'), owner='isen:2:web')
        assert st.reap(alive={'isen:2:web'}) == 1
        assert st.get(mine)['state'] == 'interrupted'
        assert st.get(theirs)['state'] == 'running', "the other panel's job was killed"

    def test_with_nothing_to_ask_every_open_row_is_closed(self):
        """The single panel is the normal case, and leaving rows open for ever is how they
        became invisible in the first place."""
        st = _hist()
        uid = st.begin(_job(), owner='erebor:1:web')
        assert st.reap(alive=None) == 1
        assert st.get(uid)['state'] == 'interrupted'

    def test_a_stale_heartbeat_is_not_a_pulse(self):
        """A process that died leaves its last one behind."""
        alive = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'record.py'))
        body = alive.split('def _alive(')[1].split(chr(10) + 'def ')[0]
        assert '_ALIVE_WITHIN' in body and 'last_seen' in body

    def test_the_panel_hands_over_the_name_it_already_calls_itself(self):
        stores = _read(os.path.join(SRC, 'lib', 'web_admin', 'mixins', 'stores.py'))
        assert '_hb_instance_id()' in stores, (
            'the jobs history invents its own idea of who this process is')


class TestAPackageTranslatesItsOwnWords:
    """Reported from the screen: opening a finished backup showed

        {'part': 'core', 'ok': True, 'tables': 42, 'rows': 20723, 'error': ''}

    A step of a copy is a dict this package composes, and only this package knows what those
    fields mean — handed over raw it reached the jobs screen as a printed Python dict, which
    is exactly what the reader saw."""

    STEPS = [{'part': 'core', 'ok': True, 'tables': 42, 'rows': 20723, 'error': ''},
             {'part': 'config_file', 'ok': True, 'tables': 0, 'rows': 1, 'error': ''},
             {'part': 'mibs', 'ok': False, 'tables': 0, 'rows': 0, 'error': 'no directory'}]

    def test_the_history_line_is_a_sentence(self):
        from lib.core.backup import jobs as backup_jobs      # noqa: PLC0415
        lines = [backup_jobs._step_line(x) for x in self.STEPS]
        assert '{' not in ' '.join(lines), 'a Python dict reached the screen again'
        assert lines[0].startswith('core') and '42 tables' in lines[0]
        assert 'ERROR' in lines[2] and 'no directory' in lines[2]

    def test_a_count_of_zero_is_not_a_count(self):
        """A part with no tables is not a part with "0 tables" — it is a part that is not
        made of tables."""
        from lib.core.backup import jobs as backup_jobs      # noqa: PLC0415
        assert 'tables' not in backup_jobs._step_line(self.STEPS[1])

    def test_the_live_columns_carry_the_verdict(self):
        from lib.core.backup import jobs as backup_jobs      # noqa: PLC0415
        rows = [backup_jobs._step_row(x) for x in self.STEPS]
        assert [r['state'] for r in rows] == ['ok', 'ok', 'failed']
        assert rows[0]['text'] == 'core' and '20723 rows' in rows[0]['note']

    def test_something_that_is_not_a_step_does_not_crash_it(self):
        from lib.core.backup import jobs as backup_jobs      # noqa: PLC0415
        assert backup_jobs._step_line('plain') == 'plain'
        assert backup_jobs._step_row(None)['text'] == ''


class TestEveryKindOfWorkSaysWhatItIs:

    def test_each_kind_has_a_word_in_both_languages(self):
        """A row reading `mib_compile` is the panel showing an internal name. The fallback is
        deliberate — a kind nothing has translated is still a job worth listing — but the ones
        that exist today are not supposed to need it."""
        from lib.i18n.lang import en_EN, es_ES              # noqa: PLC0415
        for kind in ('collect', 'backup', 'restore', 'mib_compile', 'snmp_test', 'other'):
            for mod, lang in ((es_ES, 'es_ES'), (en_EN, 'en_EN')):
                key = 'jobs_kind_' + kind
                assert mod.LANG.get(key), f'{key} has no word in {lang}'


def _hist():
    return JobHistoryStore(get_connector(None, default_sqlite_path=':memory:'))


def _job(**over):
    job = {'id': 'j1', 'kind': 'collect', 'source': 'infra', 'label': 'erebor',
           'state': 'done', 'started': 100.0, 'ended': 160.0, 'done': 24, 'total': 24,
           'error': ''}
    job.update(over)
    return job


class TestWhatEachJobDid:
    """The live list answers "what is happening". This answers "what happened" — and until it
    existed nothing did: every job lived in a dict in the process that ran it, the collections
    were forgotten half an hour after they ended and the rest went with the next restart."""

    def test_a_finished_job_comes_back_whole(self):
        st = _hist()
        uid = st.record(_job(), ['leyendo 1/24', 'leyendo 24/24'])
        got = st.get(uid)
        assert got['label'] == 'erebor' and got['state'] == 'done'
        assert got['done'] == 24 and got['total'] == 24
        assert got['log'] == ['leyendo 1/24', 'leyendo 24/24']
        assert got['ended_at'] - got['started_at'] == 60.0, 'how long it took is derivable'

    def test_the_end_of_a_long_log_is_what_is_kept(self):
        """A log is read from the end, which is where whatever went wrong is."""
        st = _hist()
        uid = st.record(_job(), [f'line {i}' for i in range(10)], cap=3)
        got = st.get(uid)
        assert got['log'] == ['line 7', 'line 8', 'line 9']
        assert got['log_dropped'] == 7, 'a log that silently stops is one nobody trusts'

    def test_a_cap_of_zero_keeps_the_row_and_not_the_log(self):
        st = _hist()
        got = st.get(st.record(_job(), ['a', 'b'], cap=0))
        assert got['log'] == [] and got['log_dropped'] == 2

    def test_blank_lines_are_not_lines(self):
        st = _hist()
        got = st.get(st.record(_job(), ['a', '', '   ', 'b']))
        assert got['log'] == ['a', 'b']

    def test_the_list_does_not_carry_the_logs(self):
        """A hundred rows with a couple of hundred lines each is a megabyte of JSON to draw a
        table of names and dates."""
        st = _hist()
        st.record(_job(), ['x' * 100] * 50)
        row = st.list()[0]
        assert 'log' not in row
        assert row['log_lines'] == 50, 'but it says there is one to open'

    def test_newest_first_and_filtered_by_what_it_was(self):
        st = _hist()
        for i in range(4):
            st.record(_job(id=f'x{i}', ended=100 + i,
                           kind='backup' if i % 2 else 'collect',
                           state='failed' if i == 3 else 'done'))
        assert [r['job_id'] for r in st.list()] == ['x3', 'x2', 'x1', 'x0']
        assert [r['job_id'] for r in st.list(kind='collect')] == ['x2', 'x0']
        assert [r['job_id'] for r in st.list(state='failed')] == ['x3']

    def test_a_job_that_is_not_there(self):
        assert _hist().get('nope') is None


class TestItDoesNotGrowForEver:

    def test_the_ceiling_keeps_the_newest(self):
        st = _hist()
        for i in range(10):
            st.record(_job(id=f'x{i}', ended=100 + i))
        assert st.prune(keep=4, days=0) == 6
        assert [r['job_id'] for r in st.list()] == ['x9', 'x8', 'x7', 'x6']

    def test_the_age_limit_is_a_second_question(self):
        """How far back anybody looks, as opposed to the ceiling a busy day hits."""
        import time as _t
        st = _hist()
        st.record(_job(id='old', ended=_t.time() - 40 * 86400))
        st.record(_job(id='new', ended=_t.time()))
        st.prune(keep=0, days=30)
        assert [r['job_id'] for r in st.list()] == ['new']

    def test_no_limits_forget_nothing(self):
        st = _hist()
        for i in range(5):
            st.record(_job(id=f'x{i}', ended=100 + i))
        assert st.prune(keep=0, days=0) == 0
        assert st.count() == 5


class TestFilingItNeverBreaksTheWorkThatJustEnded:

    def test_an_unwritable_store_answers_and_does_not_raise(self):
        """A job that finished is a job that finished: failing to write the note about it must
        not turn a completed backup into an exception in the thread that took it."""
        class _Broken:
            def reconcile_table(self, _s):
                pass

            def transaction(self):
                raise RuntimeError('the disk is full')

        assert JobHistoryStore(_Broken()).record(_job()) == ''

    def test_with_nothing_bound_nothing_is_written_and_it_says_so(self):
        """A worker process with no panel runs no jobs anybody started from a screen, and a
        note about them would have nowhere to go."""
        real = jobs_record._DB
        jobs_record._DB = None
        try:
            assert jobs_record.bound() is False
            assert jobs_record.store() is None
            assert jobs_record.record(_job()) == ''
        finally:
            jobs_record._DB = real

    def test_the_limits_are_the_installations(self):
        real = (jobs_record._DB, jobs_record.limits())
        try:
            jobs_record.bind(get_connector(None, default_sqlite_path=':memory:'),
                             {'keep': 7, 'days': 3, 'lines': 2})
            assert jobs_record.limits() == {'keep': 7, 'days': 3, 'lines': 2}
            got = jobs_record.store().get(jobs_record.record(_job(), ['a', 'b', 'c']))
            assert got['log'] == ['b', 'c'], 'the cap the installation set is not applied'
            jobs_record.bind(real[0], {'keep': 'nonsense'})
            assert jobs_record.limits()['keep'] == 7, 'rubbish overwrote a real limit'
        finally:
            jobs_record.bind(real[0], real[1])


class TestTheWorkArchivesItselfWhereItEnds:

    def test_a_collection_files_itself_when_it_closes(self):
        """Archiving from the screen would mean a job nobody happened to open is a job that
        never happened — and these are pruned from memory half an hour after they end."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'jobs.py'))
        finish = src.split('def _finish(')[1].split('\ndef ')[0]
        assert '_archive(job)' in finish, 'a collection ends without leaving a trace'
        assert 'def _archive(' in src and '_record.finish(' in src

    def test_a_collection_opens_its_row_before_it_starts_working(self):
        """Reported from the screen: restart the panel with a collection in flight and it was
        visible NOWHERE — gone from the live list, because that lives in the process that
        died, and never in the history, because it never finished. It did not end and it did
        not appear to have started."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'infra', 'jobs.py'))
        assert '_record.start({' in src, 'the note is still written only at the end'
        assert src.index('_record.start({') < src.index('target=_work'), (
            'the row is opened after the work is already going')

    def test_what_the_last_run_left_open_is_closed_at_boot(self):
        """Nothing can be running that this process did not start: a job is threads in one
        process and dies with it."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'record.py'))
        bind = src.split('def bind(')[1].split(chr(10) + 'def ')[0]
        assert 'st.reap(' in bind, "a restart leaves the last run's jobs open for ever"
        hist = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'history.py'))
        reap = hist.split('def reap(')[1].split(chr(10) + '    def ')[0]
        assert "'interrupted'" in reap and "'running'" in reap

    def test_a_job_still_open_is_the_present_and_not_the_past(self):
        """It is on the live list, from the memory of the package running it. In both places
        it would be one job on two screens disagreeing about which it belongs on."""
        st = _hist()
        st.begin(_job(id='now'))
        st.record(_job(id='over'))
        assert [r['job_id'] for r in st.list()] == ['over']
        assert st.count() == 1

    def test_a_restart_turns_it_into_something_visible(self):
        st = _hist()
        uid = st.begin(_job(id='now'))
        assert st.list() == []
        assert st.reap() == 1
        row = st.get(uid)
        assert row['state'] == 'interrupted' and row['ended_at'] > 0
        assert [r['job_id'] for r in st.list()] == ['now']
        assert st.reap() == 0, 'reaping twice re-closes a row that was already closed'

    def test_the_row_is_completed_and_not_duplicated(self):
        st = _hist()
        uid = st.begin(_job(id='j', total=24))
        assert st.complete(uid, _job(id='j', state='done', done=24, total=24), ['a'])
        assert st.count() == 1, 'finishing a job filed it a second time'
        row = st.get(uid)
        assert row['state'] == 'done' and row['done'] == 24 and row['log'] == ['a']

    def test_completing_a_row_that_is_not_there_is_not_an_error(self):
        st = _hist()
        assert st.complete('', _job()) is False

    def test_the_history_badge_does_not_wait_to_be_opened(self):
        """It came from the loaded list, so it stayed blank until somebody opened that tab —
        which is the one moment the number is no longer news."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'routes.py'))
        assert "summary['history'] = st.count()" in routes
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                '_render.html'))
        tabs = _fn(js, '_jobsTabsHtml')
        assert 'sum.history' in tabs

    def test_a_backup_files_itself_even_when_it_raised(self):
        """The row saying it failed is the one somebody comes looking for."""
        src = _read(os.path.join(SRC, 'lib', 'core', 'backup', 'jobs.py'))
        tail = src.split('finally:')[1]
        assert '_record.record(' in tail, 'a copy that raised leaves no note'

    def test_the_history_routes_are_gets(self):
        routes = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'routes.py'))
        assert '/api/v1/jobs/history' in routes
        assert not re.search(r"methods=\['(POST|PUT|DELETE|PATCH)'\]", routes)

    def test_no_database_is_said_out_loud(self):
        """An empty list would read as "nothing has ever run"."""
        routes = _read(os.path.join(SRC, 'lib', 'core', 'jobs', 'routes.py'))
        assert "'kept': False" in routes
        js = _read(os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials', 'jobs',
                                '_render.html'))
        assert 'jobs_past_off' in js
