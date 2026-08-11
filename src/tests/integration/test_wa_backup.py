#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The backup section through the real app: /api/v1/backups.

The service is covered on its own in ``tests/unit/test_backup_service.py``; what these guard is
the part only the app can answer — that every endpoint is behind its own permission, that the
list and the part catalogue arrive together, and that a copy made through the API can be put
back through it.

The permissions are five and not one on purpose. Downloading is not "viewing": the archive is
the whole install in one file, so whoever may fetch it holds the install. Restoring is not
"creating": it overwrites users and roles, which is to say it can hand the panel to whoever
the copy says owns it.
"""

import os

import pytest

from tests.conftest import _login

pytestmark = pytest.mark.usefixtures('client')


def _wait_job(client, job_id, timeout=20.0):
    """Poll a copy's job until it finishes, as the browser does.

    Both kinds of copy are started and not awaited — a request held open for the minutes a
    large install takes is one a proxy gives up on — so every test that wants the file on disk
    has to wait for the same thing the screen waits for.
    """
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f'/api/v1/backups/jobs/{job_id}').get_json()
        if job.get('done'):
            return job
        time.sleep(0.05)
    raise AssertionError('the job never finished')


def _restore(client, name='copia', **body):
    """Start a restore and wait for it, as the browser does.

    Started and not awaited, like the copies: a restore rewrites every table in one
    transaction, so it is the longest thing this section does.
    """
    res = client.post(f'/api/v1/backups/{name}/restore', json=body)
    assert res.status_code == 200, res.get_data(as_text=True)
    return _wait_job(client, res.get_json()['job_id'])


def _create(client, name='copia', wait=True, **body):
    body.setdefault('parts', ['core'])
    body.setdefault('secrets', True)
    res = client.post('/api/v1/backups', json={'name': name, **body})
    job = (res.get_json() or {}).get('job_id') if res.status_code == 200 else None
    if job and wait:
        _wait_job(client, job)
    return res


class TestTheListAndItsCatalogue:

    def test_the_parts_travel_with_the_list(self, client):
        """The form is drawn from this catalogue. A second list written into the template
        would be a second thing to keep in step, and the first part added would prove it."""
        _login(client)
        res = client.get('/api/v1/backups')
        assert res.status_code == 200
        body = res.get_json()
        ids = {p['id'] for p in body['parts']}
        assert {'core', 'syslog', 'mibs'} <= ids
        assert any(p['required'] for p in body['parts'])

    def test_an_install_with_no_copies_answers_with_none(self, client):
        _login(client)
        assert client.get('/api/v1/backups').get_json()['backups'] == []


class TestTheRoundTrip:

    def test_create_list_download_delete(self, client):
        _login(client)
        assert _create(client).get_json()['ok'] is True

        listed = client.get('/api/v1/backups').get_json()['backups']
        assert [b['name'] for b in listed] == ['copia']
        assert listed[0]['size'] > 0 and listed[0]['size_h']

        dl = client.get('/api/v1/backups/copia/download')
        assert dl.status_code == 200
        assert dl.data[:2] == b'PK', 'that is not a zip'

        assert client.delete('/api/v1/backups/copia').status_code == 200
        assert client.get('/api/v1/backups').get_json()['backups'] == []

    def test_a_restore_puts_the_rows_back(self, client, admin):
        """Through the API both ways, which is the only thing that says the two halves agree
        about the format."""
        _login(client)
        _create(client)
        admin._db_connector.execute('DELETE FROM users')
        admin._db_connector.commit()
        job = _restore(client, 'copia')
        assert not job.get('error'), job
        assert admin._db_connector.fetchone('SELECT COUNT(*) FROM users')[0] > 0

    def test_a_bad_name_is_refused_before_anything_is_written(self, client):
        assert _login(client)
        res = _create(client, name='../escapado')
        assert res.status_code == 400
        assert client.get('/api/v1/backups').get_json()['backups'] == []

    def test_restoring_something_that_is_not_there(self, client):
        _login(client)
        assert client.post('/api/v1/backups/nope/restore', json={}).status_code == 400


class TestEachOneHasItsOwnPermission:
    """A viewer may see that copies exist and nothing else — not fetch one, not apply one."""

    @pytest.fixture
    def viewer(self, client, admin):
        # The admin's own hash, so the fixture's password works and this test says nothing
        # about how passwords are stored — the pattern the host tests already use.
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        return client

    def test_a_viewer_cannot_even_list(self, viewer):
        """`backup_view` is granted to no built-in role: a copy is an administration tool, and
        the list alone tells an attacker what exists and when it was taken."""
        assert viewer.get('/api/v1/backups').status_code == 403

    def test_a_viewer_cannot_create_download_restore_or_delete(self, viewer):
        assert viewer.post('/api/v1/backups', json={'name': 'x'}).status_code == 403
        assert viewer.get('/api/v1/backups/x/download').status_code == 403
        assert viewer.post('/api/v1/backups/x/restore', json={}).status_code == 403
        assert viewer.delete('/api/v1/backups/x').status_code == 403


class TestItIsAllAudited:

    def _events(self, admin):
        return [e.get('event') for e in admin._audit_store.get_all(newest_first=True)]

    def test_creating_downloading_and_deleting_each_leave_a_line(self, client, admin):
        """Downloading is audited at the same weight as deleting: the file holds the whole
        install, so "who took a copy off this machine, and when" is a question the log has to
        be able to answer."""
        _login(client)
        _create(client)
        client.get('/api/v1/backups/copia/download')
        client.delete('/api/v1/backups/copia')
        ev = self._events(admin)
        assert 'backup_created' in ev
        assert 'backup_downloaded' in ev
        assert 'backup_deleted' in ev

    def test_a_failed_restore_is_audited_too(self, client, admin):
        """The most important line in the log, not the least."""
        _login(client)
        client.post('/api/v1/backups/nope/restore', json={})
        assert 'backup_restored' in self._events(admin)


class TestTheScheduleTakesCopies:
    """The runner's tick, driven directly — no thread, no waiting.

    A LIST of tasks, not one interval: configuration and inventory are worth a daily copy, the
    syslog and the MIBs perhaps weekly, and with a single interval that cannot be said without
    copying everything at the pace of the most demanding part — which is how a disk fills.
    """

    def _runner(self, admin):
        from lib.core.backup.runner import BackupRunner
        return BackupRunner(admin)

    def _task(self, admin, name, **kw):
        doc = {'name': name, 'enabled': True, 'every_hours': 24,
               'parts': ['core'], 'secrets': True, 'keep': 7, **kw}
        admin._backup_tasks_store.upsert(doc)
        return doc

    def test_no_tasks_means_nothing_happens(self, admin):
        admin._BACKUP_EVERY_HOURS = 0     # and nothing to migrate either
        assert self._runner(admin).tick()['created'] == []

    def test_a_task_takes_its_copy(self, admin):
        self._task(admin, 'diaria')
        out = self._runner(admin).tick()
        assert len(out['created']) == 1
        assert out['created'][0].startswith('auto-diaria-')

    def test_a_disabled_task_is_not_run(self, admin):
        """Disabled is an ANSWER, not a gap: it must not fall through to the migration and
        resurrect the schedule somebody just switched off."""
        self._task(admin, 'parada', enabled=False)
        admin._BACKUP_EVERY_HOURS = 24
        assert self._runner(admin).tick()['created'] == []

    def test_each_task_keeps_its_own_frequency(self, admin):
        """The whole point. The daily one comes round again a day later; the monthly one does
        not, and a tick between the two must take exactly one copy."""
        import time
        self._task(admin, 'diaria', every_hours=24)
        self._task(admin, 'mensual', every_hours=720)
        r = self._runner(admin)
        first = r.tick()
        assert len(first['created']) == 2, 'both are due when nothing exists yet'
        # A day later: only the daily one.
        later = r.tick(now_ts=time.time() + 25 * 3600)
        assert len(later['created']) == 1
        assert later['created'][0].startswith('auto-diaria-')

    def test_a_task_copies_what_it_says(self, admin):
        from lib.core.backup import service as svc
        self._task(admin, 'gorda', parts=['core', 'syslog'], secrets=False)
        self._runner(admin).tick()
        man = svc.list_backups(admin._var_dir)[0]
        assert set(man['parts']) == {'core', 'syslog'}
        assert man['secrets'] is False

    def test_retention_is_per_task(self, admin):
        """The bug this redesign exists to avoid: with one shared counter the daily task would
        prune the monthly one's copies — deleting exactly the ones that took a month to become
        worth having."""
        import os
        import time
        from lib.core.backup import service as svc
        self._task(admin, 'diaria', every_hours=24, keep=1)
        self._task(admin, 'mensual', every_hours=720, keep=1)
        r = self._runner(admin)
        root = svc.backups_dir(admin._var_dir)
        for i in range(3):
            r.tick(now_ts=time.time() + i)
            for fn in os.listdir(root):           # age everything so the next tick is due
                st = os.stat(os.path.join(root, fn))
                os.utime(os.path.join(root, fn), (st.st_atime, st.st_mtime - 25 * 3600))
        names = {b['name'] for b in svc.list_backups(admin._var_dir)}
        assert len([n for n in names if n.startswith('auto-diaria-')]) == 1
        assert len([n for n in names if n.startswith('auto-mensual-')]) >= 1,             'the daily task pruned the monthly one'

    def test_a_failure_is_audited_rather_than_swallowed(self, admin):
        """An unattended job failing in silence is worse than having no job: the copies are
        counted on precisely because nobody is watching them being made."""
        self._task(admin, 'rota')
        # A FILE where a directory has to be: makedirs fails on it, on every platform, and
        # the source stays plain text (an embedded NUL made this file unparseable).
        import tempfile
        fd, blocker = tempfile.mkstemp()
        os.close(fd)
        admin._var_dir = blocker
        self._runner(admin).tick()
        entries = [e for e in admin._audit_store.get_all(newest_first=True)
                   if e.get('event') == 'backup_created']
        assert entries and entries[0].get('detail', {}).get('ok') is False


class TestTheOldSettingsBecomeATask:
    """`backup_every_hours` and friends were the whole schedule before tasks existed. Retiring
    them outright would have turned a configured schedule into no schedule at all — and a copy
    that quietly stops being taken is discovered when it is needed."""

    def _runner(self, admin):
        from lib.core.backup.runner import BackupRunner
        return BackupRunner(admin)

    def test_a_configured_interval_migrates(self, admin):
        admin._BACKUP_EVERY_HOURS = 12
        admin._BACKUP_KEEP = 3
        admin._BACKUP_AUTO_SECRETS = False
        out = self._runner(admin).tick()
        tasks = admin._backup_tasks_store.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]['every_hours'] == 12 and tasks[0]['keep'] == 3
        assert tasks[0]['secrets'] is False
        assert out['created'], 'it migrated but did not run'

    def test_nothing_scheduled_before_migrates_nothing(self, admin):
        """An install that never had a schedule must not acquire one by upgrading."""
        admin._BACKUP_EVERY_HOURS = 0
        self._runner(admin).tick()
        assert admin._backup_tasks_store.count() == 0

    def test_it_happens_once(self, admin):
        admin._BACKUP_EVERY_HOURS = 12
        r = self._runner(admin)
        r.tick()
        r.tick()
        assert admin._backup_tasks_store.count() == 1


class TestTheFolderPicker:
    """Browsing for a folder, and making one. Gated on `config_edit` and not on a backup
    permission: it serves the CONFIG field, and whoever may edit that field can already type
    any path into it and read the outcome back from the error. The picker makes visible what
    the field already allowed."""

    def test_no_path_starts_where_the_copies_go(self, client, admin):
        import os
        _login(client)
        os.makedirs(os.path.join(admin._var_dir, 'backups'), exist_ok=True)
        body = client.get('/api/v1/backups/browse').get_json()
        assert body['path'].endswith('backups')
        assert body['readable'] is True

    def test_it_answers_folders_only(self, client, admin, tmp_path):
        """Choosing a folder is the job; every file name shown on the way is information the
        screen did not need to do it."""
        import os
        _login(client)
        os.makedirs(os.path.join(str(tmp_path), 'una'), exist_ok=True)
        open(os.path.join(str(tmp_path), 'un-fichero.txt'), 'w').close()
        names = [d['name'] for d in client.get(
            '/api/v1/backups/browse',
            query_string={'path': str(tmp_path)}).get_json()['dirs']]
        # Not an exact list: `tmp_path` is shared with the var_dir fixture, so it holds more
        # than this test put there. What matters is that the folder is in and the file is out.
        assert 'una' in names
        assert 'un-fichero.txt' not in names

    def test_an_unreadable_folder_is_an_answer_not_an_error(self, client):
        """Half the folders on a machine are unreadable to the account the panel runs as."""
        _login(client)
        res = client.get('/api/v1/backups/browse', query_string={'path': '/no/existe/en/absoluto'})
        assert res.status_code == 200
        assert res.get_json()['readable'] is False

    def test_it_says_whether_the_folder_can_be_written(self, client, tmp_path):
        """The one property that decides whether a folder can hold a backup at all."""
        _login(client)
        body = client.get('/api/v1/backups/browse',
                          query_string={'path': str(tmp_path)}).get_json()
        assert body['writable'] is True

    def test_making_a_folder(self, client, tmp_path):
        import os
        _login(client)
        res = client.post('/api/v1/backups/mkdir',
                          json={'parent': str(tmp_path), 'name': 'copias'})
        assert res.status_code == 200
        assert os.path.isdir(os.path.join(str(tmp_path), 'copias'))

    def test_a_name_that_is_a_path_is_refused(self, client, tmp_path):
        """`../x` is not a folder name, it is a way to create a directory somewhere else.
        Refused outright rather than sanitised: silently turning it into `x` would create a
        folder the operator did not ask for and did not see."""
        _login(client)
        for bad in ('../fuera', 'a/b', '..', 'C:'):
            assert client.post('/api/v1/backups/mkdir',
                               json={'parent': str(tmp_path), 'name': bad}).status_code == 400

    def test_browsing_needs_config_edit(self, client, admin):
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.get('/api/v1/backups/browse').status_code == 403
        assert client.post('/api/v1/backups/mkdir', json={}).status_code == 403


class TestTheTaskApi:
    """Tasks are records: created, renamed, disabled and deleted one at a time."""

    def test_create_list_edit_delete(self, client, admin):
        _login(client)
        res = client.put('/api/v1/backups/tasks', json={
            'name': 'Diaria', 'every_hours': 24, 'parts': ['core'], 'keep': 5})
        assert res.status_code == 200
        uid = res.get_json()['uid']

        tasks = client.get('/api/v1/backups/tasks').get_json()['tasks']
        assert len(tasks) == 1 and tasks[0]['name'] == 'Diaria' and tasks[0]['keep'] == 5

        client.put('/api/v1/backups/tasks', json={
            'uid': uid, 'name': 'Diaria', 'every_hours': 168, 'parts': ['core'], 'keep': 5})
        tasks = client.get('/api/v1/backups/tasks').get_json()['tasks']
        assert len(tasks) == 1, 'editing created a second task'
        assert tasks[0]['every_hours'] == 168

        assert client.delete(f'/api/v1/backups/tasks/{uid}').status_code == 200
        assert client.get('/api/v1/backups/tasks').get_json()['tasks'] == []

    def test_a_name_that_could_steer_the_path_is_refused(self, client):
        """The name becomes a component of every file name the task writes."""
        _login(client)
        for bad in ('', '   ', '../', '...'):
            assert client.put('/api/v1/backups/tasks',
                              json={'name': bad}).status_code == 400

    def test_the_missing_fields_come_back_filled(self, client):
        """Normalised by the store, so the form and the scheduler read a task the same way — a
        default applied in one of the two is how a task runs weekly on screen and daily on
        disk."""
        _login(client)
        client.put('/api/v1/backups/tasks', json={'name': 'Minima'})
        tk = client.get('/api/v1/backups/tasks').get_json()['tasks'][0]
        assert tk['enabled'] is True and tk['every_hours'] == 24 and tk['keep'] == 7

    def test_saving_and_deleting_are_audited(self, client, admin):
        """A task edited to run monthly instead of daily is a decision somebody made, and the
        copies that stop appearing are its consequence."""
        _login(client)
        uid = client.put('/api/v1/backups/tasks',
                         json={'name': 'Auditada'}).get_json()['uid']
        client.delete(f'/api/v1/backups/tasks/{uid}')
        events = [e.get('event') for e in admin._audit_store.get_all(newest_first=True)]
        assert 'backup_task_saved' in events and 'backup_task_deleted' in events

    def test_a_viewer_cannot_write_one(self, client, admin):
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.put('/api/v1/backups/tasks', json={'name': 'x'}).status_code == 403
        assert client.delete('/api/v1/backups/tasks/whatever').status_code == 403


class TestACalendarTask:
    """Days of the week at a time of day — the thing an interval could not say."""

    def _runner(self, admin):
        from lib.core.backup.runner import BackupRunner
        return BackupRunner(admin)

    def test_it_round_trips_through_the_api(self, client):
        _login(client)
        client.put('/api/v1/backups/tasks', json={
            'name': 'Fin de semana', 'mode': 'calendar', 'days': [5, 6], 'at': '02:30',
            'parts': ['core']})
        tk = client.get('/api/v1/backups/tasks').get_json()['tasks'][0]
        assert tk['mode'] == 'calendar' and tk['days'] == [5, 6] and tk['at'] == '02:30'

    def test_a_day_nothing_can_match_is_dropped_at_the_door(self, client):
        """A task that looks scheduled and never runs is worse than one that says it is off."""
        _login(client)
        client.put('/api/v1/backups/tasks', json={
            'name': 'Rara', 'mode': 'calendar', 'days': [9, 'lunes'], 'at': 'tres'})
        tk = client.get('/api/v1/backups/tasks').get_json()['tasks'][0]
        assert tk['days'] == [] and tk['at'] == '03:00'

    def test_an_unknown_mode_falls_back_to_interval(self, client):
        _login(client)
        client.put('/api/v1/backups/tasks', json={'name': 'X', 'mode': 'cron'})
        assert client.get('/api/v1/backups/tasks').get_json()['tasks'][0]['mode'] == 'interval'

    def test_the_runner_takes_a_calendar_copy(self, admin):
        admin._backup_tasks_store.upsert({
            'name': 'Nocturna', 'enabled': True, 'mode': 'calendar',
            'days': [], 'at': '03:00', 'parts': ['core'], 'keep': 7})
        out = self._runner(admin).tick()
        assert out['created'] and out['created'][0].startswith('auto-nocturna-')

    def test_a_task_without_a_mode_still_runs(self, admin):
        """Every task created before the calendar existed has no `mode`. They are intervals,
        and an upgrade that stopped running them would be a schedule silently switched off."""
        admin._backup_tasks_store.upsert({
            'name': 'Vieja', 'enabled': True, 'every_hours': 24, 'parts': ['core']})
        assert self._runner(admin).tick()['created']


class TestRunningATaskNow:
    """Standing in a task, "create a copy" means THAT copy. A run-now that went through the
    generic create would produce a copy the task does not own — outside its retention counter,
    never pruned by it, and not the thing somebody looking at its list asked for.

    Started and polled, not awaited: a copy of a large install takes minutes, and a request
    held open that long is one a browser or a reverse proxy eventually gives up on.
    """

    @staticmethod
    def _run(client, uid, timeout=20.0):
        """Start a run and wait for the job to finish, as the browser does."""
        res = client.post(f'/api/v1/backups/tasks/{uid}/run', json={})
        assert res.status_code == 200, res.get_data(as_text=True)
        return _wait_job(client, res.get_json()['job_id'], timeout)

    def test_it_produces_a_copy_the_task_owns(self, client, admin):
        _login(client)
        uid = client.put('/api/v1/backups/tasks', json={
            'name': 'Diaria', 'parts': ['core'], 'secrets': False}).get_json()['uid']
        job = self._run(client, uid)
        assert not job.get('error'), job
        assert job['created'].startswith('auto-diaria-'), 'the copy is not named for the task'

        from lib.core.backup import service as svc
        man = [b for b in svc.list_backups(admin._var_dir) if b['name'] == job['created']][0]
        assert man['secrets'] is False, 'it ignored the task and used the generic defaults'
        assert set(man['parts']) == {'core'}

    def test_the_job_reports_which_table_it_is_on(self, client, admin):
        """Rows are unbounded and the archive's size is unknown until it closes, so the table
        is the only unit that means anything: "syslog 4/11" is a sentence."""
        _login(client)
        uid = client.put('/api/v1/backups/tasks',
                         json={'name': 'Progreso', 'parts': ['core']}).get_json()['uid']
        job = self._run(client, uid)
        assert job['total'] > 0, 'nothing was reported to count against'

    def test_running_applies_the_tasks_retention(self, client, admin):
        """The same path as the schedule, retention included — otherwise "run now" is a way to
        fill the disk with copies nothing counts."""
        import time
        _login(client)
        uid = client.put('/api/v1/backups/tasks', json={
            'name': 'Corta', 'parts': ['core'], 'keep': 1}).get_json()['uid']
        from lib.core.backup import service as svc
        for _ in range(3):
            self._run(client, uid)
            time.sleep(1.05)      # the name carries seconds; two in one second collide
        kept = [b for b in svc.list_backups(admin._var_dir)
                if b['name'].startswith('auto-corta-')]
        assert len(kept) == 1, f'retention did not apply: {[b["name"] for b in kept]}'

    def test_an_unknown_task_is_a_404(self, client):
        _login(client)
        assert client.post('/api/v1/backups/tasks/nope/run', json={}).status_code == 404

    def test_an_unknown_job_is_a_404_not_a_wait(self, client):
        """Jobs live in memory, so one started before a restart is genuinely gone — the browser
        should stop asking rather than wait for an answer that will never come."""
        _login(client)
        assert client.get('/api/v1/backups/jobs/nope').status_code == 404

    def test_a_viewer_cannot_run_one(self, client, admin):
        admin._users['viewer'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'viewer', 'display_name': 'V'}
        _login(client, 'viewer')
        assert client.post('/api/v1/backups/tasks/x/run', json={}).status_code == 403


class TestAHandMadeCopyIsWatchedToo:
    """Reported: "la copia manual no muestra la barra de progreso, solo se muestra cuando
    termina". It was awaited — the request held the connection for the whole copy, so there was
    nothing to show a bar against, and on an install whose syslog table is six figures of rows
    that is a minute of a screen that looks broken.

    Same job as the scheduled runs, so the row, the bar and the dialog are the ones that
    already exist rather than a second implementation of them.
    """

    def test_it_answers_a_job_and_not_a_finished_copy(self, client):
        _login(client)
        res = client.post('/api/v1/backups', json={'name': 'amano', 'parts': ['core']})
        assert res.status_code == 200
        body = res.get_json()
        assert body.get('job_id'), 'the request still waits for the whole copy'

    def test_the_job_ends_with_the_copy_on_disk(self, client, admin):
        _login(client)
        job = _wait_job(client, client.post(
            '/api/v1/backups', json={'name': 'amano', 'parts': ['core']}).get_json()['job_id'])
        assert not job.get('error'), job
        assert job['created'] == 'amano'
        assert job['manual'] is True, 'the screen cannot tell it apart from a scheduled run'
        from lib.core.backup import service as svc
        assert any(b['name'] == 'amano' for b in svc.list_backups(admin._var_dir))

    def test_it_reports_what_it_is_copying(self, client):
        """A bar needs a denominator, and a name for the step tells the operator whether it is
        stuck or simply on the big table."""
        _login(client)
        job = _wait_job(client, client.post(
            '/api/v1/backups', json={'name': 'amano', 'parts': ['core']}).get_json()['job_id'])
        assert job['total'] > 0
        assert job['steps'], 'the checklist is empty, so the dialog has nothing to tick'

    def test_the_line_names_who_asked_for_it(self, admin, client):
        """The work happens on a thread with no request, and auditing it as `system` would lose
        the one fact this entry exists to record — so the actor is read in the route and
        carried in."""
        _login(client)
        _create(client, name='amano')
        row = next(e for e in admin._audit_store.get_all(newest_first=True)
                   if e.get('event') == 'backup_created')
        assert row.get('user') == 'admin', row

    def test_a_copy_that_could_not_be_written_says_so_in_the_job(self, client, admin):
        """A name already taken is refused by the service, not by the route — and the browser
        only ever sees the job, so a failure that never reached it would look like success."""
        _login(client)
        _create(client, name='amano')
        job = _wait_job(client, client.post(
            '/api/v1/backups', json={'name': 'amano', 'parts': ['core']}).get_json()['job_id'])
        assert job['error'], 'the second copy silently overwrote or silently did nothing'


class TestRestoringACopyFromAnotherBuild:
    """Nothing is refused over a version — the schema moves on almost every build. What the
    API has to do is SAY which way the jump goes, and what the live schema could not take."""

    def test_the_list_says_how_the_copy_relates_to_this_install(self, client):
        _login(client)
        _create(client)
        b = client.get('/api/v1/backups').get_json()['backups'][0]
        assert b['version_rel'] == 'same', b
        assert client.get('/api/v1/backups').get_json()['version'], \
            'the dialog cannot name this install'

    def test_what_could_not_be_restored_comes_back_and_is_logged(self, client, admin):
        """The log especially: a restore is the moment nobody is looking ten minutes later."""
        _login(client)
        _create(client)
        admin._db_connector.execute('DROP TABLE credentials')
        admin._db_connector.commit()
        job = _restore(client, 'copia')
        assert job['skipped']['credentials']['missing'] is True

        row = next(e for e in admin._audit_store.get_all(newest_first=True)
                   if e.get('event') == 'backup_restored')
        detail = row.get('detail')
        assert 'credentials' in str(detail) and 'from_version' in str(detail)


class TestARestoreIsWatchedWhileItHappens:
    """It used to be awaited. On an install whose tables run to six figures of rows that is a
    screen saying nothing while every one of them is replaced — the moment where silence is
    most alarming, because what it is silent about is the install being overwritten."""

    def test_it_answers_a_job_and_not_a_finished_restore(self, client):
        _login(client)
        _create(client)
        body = client.post('/api/v1/backups/copia/restore', json={}).get_json()
        assert body.get('job_id'), 'the request still holds the connection for the whole thing'

    def test_the_job_says_which_table_it_is_on(self, client):
        _login(client)
        _create(client)
        job = _restore(client, 'copia')
        assert job['kind'] == 'restore', 'the screen cannot tell it from a copy'
        assert job['total'] > 0, 'nothing to draw a bar against'
        assert job['tables'], 'the outcome never reached the job'

    def test_a_copy_that_is_not_there_is_refused_before_any_of_it_starts(self, client, admin):
        """A progress bar for something that was never going to happen is worse than an
        error — and the attempt is still worth a line in the log."""
        _login(client)
        res = client.post('/api/v1/backups/nope/restore', json={})
        assert res.status_code == 400
        assert 'job_id' not in (res.get_json() or {})
        assert 'backup_restored' in [e.get('event')
                                     for e in admin._audit_store.get_all(newest_first=True)]


class TestTheScheduleAndTheVerifyAreTheirOwnGrants:
    """Changing the schedule destroys no archive and quietly halves the protection; verifying
    writes nothing and hashes every member of a multi-gigabyte copy. Neither is what
    `backup_create` or `backup_view` were granted for."""

    @pytest.fixture
    def keeper(self, client, admin):
        """Everything a backup operator has, EXCEPT the two new ones."""
        admin._custom_roles['keeper'] = {'label': 'Keeper', 'permissions': [
            'backup_view', 'backup_create', 'backup_download', 'backup_restore',
            'backup_delete']}
        admin._users['keeper'] = {'password_hash': admin._users['admin']['password_hash'],
                                  'role': 'keeper', 'display_name': 'K'}
        _login(client, 'keeper')
        return client

    def test_taking_copies_does_not_grant_changing_the_schedule(self, keeper):
        assert keeper.put('/api/v1/backups/tasks',
                          json={'name': 'Diaria'}).status_code == 403
        assert keeper.delete('/api/v1/backups/tasks/x').status_code == 403

    def test_seeing_copies_does_not_grant_verifying_them(self, keeper):
        assert keeper.post('/api/v1/backups/x/verify', json={}).status_code == 403

    def test_it_can_still_do_what_it_was_granted(self, keeper):
        """The point is a narrower grant, not a broken one."""
        assert keeper.get('/api/v1/backups').status_code == 200
        assert _create(keeper).status_code == 200

    def test_running_a_task_needs_only_the_copy_grant(self, client, admin):
        """Running a task produces a copy, exactly like the Create button — one grant should
        not be two ways to the same result."""
        _login(client)
        uid = client.put('/api/v1/backups/tasks',
                         json={'name': 'Diaria', 'parts': ['core']}).get_json()['uid']
        admin._custom_roles['maker'] = {'label': 'Maker',
                                        'permissions': ['backup_view', 'backup_create']}
        admin._users['maker'] = {'password_hash': admin._users['admin']['password_hash'],
                                 'role': 'maker', 'display_name': 'M'}
        _login(client, 'maker')
        assert client.post(f'/api/v1/backups/tasks/{uid}/run', json={}).status_code == 200
