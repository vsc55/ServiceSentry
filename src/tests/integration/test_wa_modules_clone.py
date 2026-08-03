#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cloning an item stored it and reported failure — the two halves of that.

Reported against m365, true of every module: create an item and it saves; clone it, rename
it, save, and the record IS written while the screen says "Error al guardar", the Save button
stays lit as though nothing had gone through, and the audit shows neither the save nor the
error. The worst shape a bug can take — the user's next move is to save again, or to undo a
change that was already persisted.

Two separate defects lined up to produce it:

1. **The clone kept the original's uid.** ``cloneItem`` deep-copied the item verbatim, and a
   uid is identity, not data. The server generates one only when absent, so the copy arrived
   claiming to be the original. Re-keying repairs that (it hands the second item a fresh uid),
   but the arrival is still recorded as a duplicate — so a routine clone tripped the alarm
   built to catch real corruption.

2. **Recording the duplicate crashed the request.** ``_diff_dicts`` returns ``[{field, old,
   new}]`` and the note was appended with ``+`` as if it were a string: ``TypeError``, raised
   AFTER ``_save_modules`` had already committed and BEFORE the audit line ran. Hence all
   three symptoms at once: stored, "failed", unaudited.

So the guards come in pairs. The endpoint must survive a duplicate uid whatever put it there —
an imported config or a hand-edited file can still carry one — and the UI must stop
manufacturing them.
"""

import io
import json
import os
import re

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
FIELD_OPS = os.path.join(SRC, 'lib', 'web_admin', 'templates', 'partials',
                         'actions', '_field_ops.html')


def _fn(src: str, name: str) -> str:
    m = re.search(r'^(?:async )?function ' + re.escape(name) + r'\([^)]*\)\s*\{(.*?)^\}',
                  src, re.S | re.M)
    assert m, f'{name} is gone — this guard needs updating with whatever replaced it'
    return m.group(1)


class TestSavingACloneReportsWhatHappened:
    """The endpoint half, walked through the real route: a payload carrying a duplicate uid
    is exactly what the UI used to send, and it must save, answer 200, and audit."""

    @staticmethod
    def _seed(client):
        """One item, saved, then read back so its key is the uid the server assigned."""
        r = client.put('/api/v1/modules', json={'ping': {'enabled': True, 'list': {
            'a': {'label': 'original', 'enabled': True}}}})
        assert r.status_code == 200, r.get_json()
        return client.get('/api/v1/modules').get_json()

    def test_a_duplicate_uid_does_not_fail_the_request(self, client):
        """The crash: `list + str`. It fired after the write, so the item was already stored
        when the browser was told the save had failed."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        data = self._seed(client)
        items = data['ping']['list']
        uid = next(iter(items))
        copy = json.loads(json.dumps(items[uid]))   # verbatim — uid and all
        copy['label'] = 'clone'
        items['a_copy'] = copy

        r = client.put('/api/v1/modules', json=data)
        assert r.status_code == 200, f'{r.status_code}: {r.data[:400]}'
        assert (r.get_json() or {}).get('ok') is True

    def test_both_items_survive_and_get_their_own_uid(self, client):
        """Re-keying resolves the collision by GIVING one a new uid, never by dropping it."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        data = self._seed(client)
        items = data['ping']['list']
        uid = next(iter(items))
        copy = json.loads(json.dumps(items[uid]))
        copy['label'] = 'clone'
        items['a_copy'] = copy
        client.put('/api/v1/modules', json=data)

        got = client.get('/api/v1/modules').get_json()['ping']['list']
        assert len(got) == 2, f'an item was lost: {got}'
        assert {v['label'] for v in got.values()} == {'original', 'clone'}
        assert len(set(got)) == 2, 'the two items ended up sharing a key'
        assert all(v.get('uid') == k for k, v in got.items()), \
            'an item\'s key stopped being its uid'

    def test_the_save_is_audited_with_the_duplicate_noted(self, admin, client):
        """Neither half of the record may go missing: the save is audited, and the duplicate
        rides in the SAME entry — that is the record somebody reads when an item moved."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        data = self._seed(client)
        items = data['ping']['list']
        uid = next(iter(items))
        copy = json.loads(json.dumps(items[uid]))
        copy['label'] = 'clone'
        items['a_copy'] = copy
        client.put('/api/v1/modules', json=data)

        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        assert isinstance(entry['detail'], list), \
            f'the change list stopped being a list: {entry["detail"]!r}'
        note = [c for c in entry['detail'] if 'duplicate' in str(c.get('field', ''))]
        assert note, f'the duplicate went unrecorded: {entry["detail"]}'
        assert uid in str(note[0]['new']), 'the note does not say WHICH uid'

    def test_an_ordinary_save_is_still_a_plain_change_list(self, admin, client):
        """The note is added, not substituted: a save with no duplicate must look exactly as
        it did before — the audit UI renders `[{field, old, new}]` as a table."""
        from tests.conftest import _login                        # noqa: PLC0415
        _login(client)
        client.put('/api/v1/modules', json={'ping': {'enabled': False, 'threads': 5}})
        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        assert isinstance(entry['detail'], list)
        assert all(set(c) == {'field', 'old', 'new'} for c in entry['detail']), entry['detail']
        assert not any('duplicate' in str(c['field']) for c in entry['detail'])






