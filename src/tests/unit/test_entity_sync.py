#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A save writes what changed — and, above all, does not touch what it never saw.

Roles, users and groups were written back with ``DELETE FROM <table>`` followed by
re-inserting every row from memory.  That is correct while one process owns the database
and destructive the moment two do: two admins on two replicas editing *different* roles do
not lose a field each — the one who saves second deletes the other's role and restores the
table as it looked in ITS memory.  Nothing fails and nothing is logged.

The rule that fixes it is about deletions, not updates: a row may only be deleted if this
process **had** it and no longer does.  A row that appeared while we were editing belongs
to somebody else.

The scenarios below are two stores over one database, which is exactly what a second
replica — or the CLI next to a running panel — is.
"""

import pytest

try:
    from lib.web_admin import WebAdmin          # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from lib.core.entity_sync import diff_entities, snapshot

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason='Flask is not installed')


class TestTheDiff:
    """Pure, and small enough to state exhaustively."""

    def test_an_unchanged_row_is_not_written(self):
        rows = {'a': {'name': 'A'}}
        assert diff_entities(rows, {'a': {'name': 'A'}}) == ({}, [])

    def test_a_changed_row_is_written(self):
        writes, deletes = diff_entities({'a': {'name': 'A'}}, {'a': {'name': 'B'}})
        assert writes == {'a': {'name': 'B'}} and deletes == []

    def test_a_new_row_is_written(self):
        writes, deletes = diff_entities({}, {'a': {'name': 'A'}})
        assert writes == {'a': {'name': 'A'}} and deletes == []

    def test_a_row_we_had_and_dropped_is_deleted(self):
        writes, deletes = diff_entities({'a': {'name': 'A'}}, {})
        assert writes == {} and deletes == ['a']

    def test_the_first_save_of_all_writes_nothing_away(self):
        """No snapshot yet (first run) means "I know of nothing", so nothing is deleted."""
        writes, deletes = diff_entities(None, {'a': {'name': 'A'}})
        assert writes == {'a': {'name': 'A'}} and deletes == []

    def test_the_snapshot_does_not_share_its_lists(self):
        """A shallow copy would share the permission list a role edits in place: the
        snapshot would change with the live data and every diff would say "nothing
        changed" — the bug that turns this whole mechanism into a no-op."""
        live = {'r': {'permissions': ['users_view']}}
        snap = snapshot(live)
        live['r']['permissions'].append('users_delete')
        assert snap['r']['permissions'] == ['users_view']
        assert diff_entities(snap, live)[0]


