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

import pytest

from tests.conftest import _login

pytestmark = pytest.mark.usefixtures('client')


def _create(client, name='copia', **body):
    body.setdefault('parts', ['core'])
    body.setdefault('secrets', True)
    return client.post('/api/v1/backups', json={'name': name, **body})


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
        res = client.post('/api/v1/backups/copia/restore', json={})
        assert res.status_code == 200 and res.get_json()['ok'] is True
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

    What it guards is the part the pure schedule functions cannot: that a due copy is actually
    written, that retention deletes the right ones, and that the two happen in the order that
    survives a full disk.
    """

    def _runner(self, admin, every=24, keep=7):
        from lib.core.backup.runner import BackupRunner
        admin._BACKUP_EVERY_HOURS = every
        admin._BACKUP_KEEP = keep
        admin._BACKUP_AUTO_SECRETS = True
        return BackupRunner(admin)

    def test_a_tick_with_the_schedule_off_does_nothing(self, admin):
        out = self._runner(admin, every=0).tick()
        assert out['due'] is False and out['created'] == ''

    def test_the_first_tick_takes_one(self, admin):
        """An install that has never taken a copy is the one that most needs it."""
        out = self._runner(admin).tick()
        assert out['created'].startswith('auto-')

    def test_a_second_tick_inside_the_interval_takes_none(self, admin):
        r = self._runner(admin)
        assert r.tick()['created']
        assert r.tick()['created'] == '', 'it copied again inside the interval'

    def test_the_scheduled_copy_leaves_the_bulky_parts_out(self, admin):
        """An unattended job that quietly writes 160k syslog rows every day is how the disk
        fills. Those parts are what an operator opts into for a copy they are making
        themselves."""
        from lib.core.backup import service as svc
        self._runner(admin).tick()
        man = svc.list_backups(admin._var_dir)[0]
        assert set(man['parts']) == {'core', 'config_file'}
        assert man['secrets'] is True, 'an unattended copy with no credentials is a trap'

    def test_retention_deletes_the_oldest_and_keeps_the_hand_made_one(self, admin):
        """Time is simulated by AGEING the files, not by passing a fake clock: "when was the
        last one" is read from their mtimes, so a fake now and real mtimes describe two
        different moments and the second tick would find itself in the past."""
        import os
        import time
        from lib.core.backup import service as svc
        r = self._runner(admin, keep=2)
        # A copy somebody took by hand, which retention must never touch.
        svc.create_backup(admin._db_connector, 'antes-de-actualizar',
                          var_dir=admin._var_dir, config_dir='', parts=['core'],
                          include_secrets=True)
        root = svc.backups_dir(admin._var_dir)
        for i in range(3):
            r.tick(now_ts=time.time() + i)      # +i so two copies never share a name
            # Push everything a day into the past so the next tick is due again.
            for fn in os.listdir(root):
                p = os.path.join(root, fn)
                st = os.stat(p)
                os.utime(p, (st.st_atime, st.st_mtime - 25 * 3600))
        names = {b['name'] for b in svc.list_backups(admin._var_dir)}
        assert 'antes-de-actualizar' in names, 'retention pruned a copy a person made'
        assert len([n for n in names if n.startswith('auto-')]) == 2

    def test_a_failure_is_audited_rather_than_swallowed(self, admin):
        """An unattended job failing in silence is worse than having no job: the copies are
        counted on precisely because nobody is watching them being made."""
        r = self._runner(admin)
        admin._var_dir = '\x00 not a path'      # create_backup will fail on it
        r.tick()
        entries = [e for e in admin._audit_store.get_all(newest_first=True)
                   if e.get('event') == 'backup_created']
        assert entries and entries[0].get('detail', {}).get('ok') is False


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
