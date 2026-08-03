#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the flask-free entity audit-stamp helpers (``lib.util.entity_audit``).

``touch_entity``/``track_change`` are pure (no Flask, no request context): the
caller resolves the acting user and passes it in.
"""

from lib.util.entity_audit import touch_entity


class TestTouchEntity:

    def test_stamps_updated_fields(self):
        entity = {}
        touch_entity(entity, 'admin')   # actor resolved by the caller (was flask.session)
        assert entity['updated_by'] == 'admin'
        assert entity['updated_at'].endswith(('Z', '+00:00')) or 'T' in entity['updated_at']


class TestTrackChange:

    def test_records_and_applies_change(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {'name': 'old'}
        track_change(changes, entity, 'name', 'new')
        assert entity['name'] == 'new'
        assert changes == [{'field': 'name', 'old': 'old', 'new': 'new'}]

    def test_no_change_no_record(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {'name': 'same'}
        track_change(changes, entity, 'name', 'same')
        assert changes == [] and entity['name'] == 'same'

    def test_old_default(self):
        from lib.util.entity_audit import track_change
        changes, entity = [], {}
        track_change(changes, entity, 'name', 'new', old_default='uid-x')
        assert changes == [{'field': 'name', 'old': 'uid-x', 'new': 'new'}]
        assert entity['name'] == 'new'
