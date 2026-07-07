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
