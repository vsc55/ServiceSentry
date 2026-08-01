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

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


class TestTheUiStopsManufacturingDuplicates:
    """The other half. The endpoint now survives a duplicate uid, but a clone should never
    produce one: the alarm exists to catch corruption, and an alarm that fires on a routine
    action is one nobody reads."""

    @staticmethod
    def _src() -> str:
        return io.open(FIELD_OPS, encoding='utf-8-sig').read()

    def test_clone_strips_the_uid(self):
        body = _fn(self._src(), '_doCloneItem')
        assert '_stripItemUids' in body, \
            'the clone copies the item verbatim again — it claims the original\'s uid'

    def test_the_strip_reaches_nested_items(self):
        """An item can hold its own collection of items (snmp's per-server `checks`), keyed
        by uid on the server too — a shallow strip would collide once per nested check."""
        body = _fn(self._src(), '_stripItemUids')
        assert '_stripItemUids' in body, 'the strip stopped recursing into nested values'
        assert 'Array.isArray' in body, 'a list of items would be walked past'

    def test_references_are_not_stripped(self):
        """`cred_uid` and `host_uid` are references, not identity: the copy must go on
        pointing at the same credential and the same host. Deleting anything ending in `uid`
        would silently unbind every clone."""
        body = _fn(self._src(), '_stripItemUids')
        assert 'delete value.uid' in body, 'the strip is no longer by exact name'
        assert 'cred_uid' not in body.replace('//', '\n//').split('\n//')[0], \
            'a reference field is being deleted'


class TestTheNameIsAskedForBeforeAnythingIsCopied:
    """Cloning on the click left two rows under one label with no way to tell them apart, and
    no way back — the copy already existed, so undoing meant Discard or Undo. Asking first
    makes Cancel mean what it says."""

    @staticmethod
    def _src() -> str:
        return io.open(FIELD_OPS, encoding='utf-8-sig').read()

    def test_the_click_only_opens_the_modal(self):
        body = _fn(self._src(), 'cloneItem')
        assert 'Modal' in body and 'show()' in body, 'the click stopped opening the modal'
        for verb in ('JSON.stringify(parent[key])', 'markDirty', 'showToast'):
            assert verb not in body, \
                f'cloneItem does {verb} on the click again — Cancel would not undo it'

    def test_accepting_is_what_copies(self):
        body = _fn(self._src(), '_doCloneItem')
        assert 'markDirty' in body and 'showToast' in body, \
            'accepting no longer performs the clone'

    def test_a_blank_or_taken_name_is_refused(self):
        """Refused in the modal, where it can be corrected — not accepted and then discovered
        on screen as the second row with the same name."""
        body = _fn(self._src(), '_doCloneItem')
        assert 'clone_name_required' in body, 'an empty name would be accepted'
        assert 'clone_name_exists' in body, 'a duplicate name would be accepted'

    def test_the_proposal_counts_up_from_the_base_name(self):
        """`web_Copia1` cloned proposes `web_Copia2`, not `web_Copia1_Copia1`: the suffix
        marks a copy, it is not part of the name."""
        body = _fn(self._src(), '_proposeCloneName')
        assert 'replace(' in body, 'the existing copy suffix is no longer trimmed'
        assert 'while' in body and 'taken' in body, 'it stopped looking for a free number'

    def test_the_proposal_compares_display_names(self):
        """Keys cannot collide anyway — the whole point is that two identical LABELS leave the
        user unable to tell the rows apart."""
        body = _fn(self._src(), '_proposeCloneName')
        assert '_itemDisplayName' in body, 'it went back to comparing dict keys'

    def test_the_typed_name_reaches_the_right_place(self):
        """Two kinds of collection: some hold the name in a field, some in the dict key.
        Writing to the wrong one shows the OLD name on the new row — the exact confusion this
        change exists to remove."""
        body = _fn(self._src(), '_doCloneItem')
        assert '_itemTitleField' in body, \
            'the clone stopped asking where this collection keeps its names'

    def test_reading_and_writing_a_name_use_one_helper(self):
        """They must not drift. `_itemDisplayName` reads through `_itemTitleField`, and the
        clone writes through it — one definition of where a name lives."""
        assert '_itemTitleField' in _fn(self._src(), '_itemDisplayName')

    def test_a_saved_item_that_gained_a_label_is_field_named(self):
        """The trap: collections keyed by a hostname have no declared title field, but the
        server's re-key turns the key into a uid and stamps the old key into `label` — which
        is then what the list shows. Deciding from the schema alone would write the typed
        name into a key nobody displays, and the copy would keep the original's name."""
        body = _fn(self._src(), '_itemTitleField')
        assert "'label' in item" in body, \
            'it decides from the schema alone again — a re-keyed item loses the typed name'

    def test_the_copy_declares_where_it_came_from(self):
        body = _fn(self._src(), '_doCloneItem')
        assert '__cloned_from__' in body, \
            'the clone no longer tells the server it is a copy — the audit cannot say so'


class TestTheAuditSaysNewOrClonedAndFromWhat:
    """Asked for directly: the audit should record whether an item is new or a clone, and for
    a clone, its source. `_diff_dicts` reports the new item's fields the same way either way,
    which is precisely the distinction somebody comparing two near-identical rows needs."""

    def test_the_mark_never_reaches_storage(self):
        """It answers a question about the WRITE. Persisted, it would become a permanent
        property of the item instead of a fact about the moment it was created."""
        from lib.core.modules.service import take_clone_marks       # noqa: PLC0415
        data = {'ping': {'list': {'U2': {'uid': 'U2', '__cloned_from__': 'U1'}}}}
        marks = take_clone_marks(data)
        assert marks == {('ping', 'list', 'U2'): 'U1'}
        assert '__cloned_from__' not in data['ping']['list']['U2']

    def test_an_unmarked_item_yields_no_mark(self):
        from lib.core.modules.service import take_clone_marks       # noqa: PLC0415
        data = {'ping': {'list': {'U1': {'uid': 'U1'}}}}
        assert take_clone_marks(data) == {}
        assert data == {'ping': {'list': {'U1': {'uid': 'U1'}}}}

    def test_a_new_item_is_reported_as_new(self):
        from lib.core.modules.service import item_origin_rows       # noqa: PLC0415
        rows = item_origin_rows({}, {'ping': {'list': {'U1': {'label': 'web'}}}}, {})
        assert len(rows) == 1
        assert rows[0]['field'] == 'ping.list · new item'
        assert 'web' in rows[0]['new'] and 'U1' in rows[0]['new']

    def test_a_clone_names_its_source(self):
        from lib.core.modules.service import item_origin_rows       # noqa: PLC0415
        old = {'ping': {'list': {'U1': {'label': 'web'}}}}
        new = {'ping': {'list': {'U1': {'label': 'web'},
                                 'U2': {'label': 'web_Copia1'}}}}
        rows = item_origin_rows(old, new, {('ping', 'list', 'U2'): 'U1'})
        assert len(rows) == 1, rows
        assert rows[0]['field'] == 'ping.list · cloned item'
        assert 'web' in rows[0]['old'] and 'U1' in rows[0]['old'], rows[0]
        assert 'web_Copia1' in rows[0]['new']

    def test_an_untouched_item_produces_no_row(self):
        """Only items that APPEARED. An edit is already reported field by field."""
        from lib.core.modules.service import item_origin_rows       # noqa: PLC0415
        same = {'ping': {'list': {'U1': {'label': 'web'}}}}
        assert item_origin_rows(same, same, {}) == []

    def test_the_name_comes_from_what_the_module_declares(self):
        """Modules do not all call it `label` — ups uses `ups_name`, process uses `process`.
        Guessing would silently print a uid for those."""
        from lib.core.modules.service import item_origin_rows       # noqa: PLC0415
        rows = item_origin_rows(
            {}, {'ups': {'list': {'U1': {'ups_name': 'sai-1'}}}}, {},
            {'ups|list': {'__check_title_field__': 'ups_name'}})
        assert 'sai-1' in rows[0]['new'], rows[0]

    def test_it_survives_discovery_being_unavailable(self):
        """Naming an item is a nicety; a module folder that fails to scan must not be why a
        save 500s. Empty, never an exception — and the caller then falls back to `label`."""
        from lib.core.modules.service import item_schemas           # noqa: PLC0415
        assert item_schemas('/definitely/not/a/directory') == {}
        assert item_schemas(None), 'the real scan came back empty — the fallback hides that'

    def test_a_missing_schema_still_names_what_it_can(self):
        """With no schema at all the rows must still be readable: `label` is what the rest of
        the UI assumes, and the uid is always there."""
        from lib.core.modules.service import item_origin_rows       # noqa: PLC0415
        rows = item_origin_rows({}, {'x': {'list': {'U9': {'label': 'thing'}}}}, {}, {})
        assert 'thing' in rows[0]['new'] and 'U9' in rows[0]['new']
        bare = item_origin_rows({}, {'x': {'list': {'U9': {}}}}, {}, {})
        assert bare[0]['new'] == 'U9', bare[0]

    def test_the_audit_entry_carries_the_origin(self, admin, client):
        """End to end through the real route: the mark rides in the payload and comes out the
        other side as a row a reader can act on."""
        from tests.conftest import _login                           # noqa: PLC0415
        _login(client)
        client.put('/api/v1/modules', json={'ping': {'enabled': True, 'list': {
            'a': {'label': 'origin', 'enabled': True}}}})
        data = client.get('/api/v1/modules').get_json()
        items = data['ping']['list']
        uid = next(iter(items))
        items['a_copy'] = {'label': 'origin_Copia1', 'enabled': True,
                           '__cloned_from__': uid}
        client.put('/api/v1/modules', json=data)

        entry = [e for e in admin._audit_log if e['event'] == 'modules_saved'][-1]
        row = [c for c in entry['detail'] if 'cloned item' in str(c.get('field', ''))]
        assert row, f'the clone was not reported as one: {entry["detail"]}'
        assert 'origin' in row[0]['old'], row[0]
        assert 'origin_Copia1' in row[0]['new'], row[0]

        stored = client.get('/api/v1/modules').get_json()['ping']['list']
        assert not any('__cloned_from__' in v for v in stored.values()), \
            'the clone mark was persisted into the configuration'
