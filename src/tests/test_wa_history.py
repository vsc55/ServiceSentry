#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the History API routes — focus on the friendly series label."""

import json

from tests.conftest import _login


def test_index_label_from_item_label(client, admin):
    """A series whose key matches a configured item shows that item's label."""
    if admin._history is None:
        return  # history store unavailable in this environment
    # Find ping's "Router" item by its (possibly migration-rekeyed) UID key.
    mods = admin._load_modules()
    ping_items = (mods.get('ping') or {}).get('list') or {}
    key = next(k for k, v in ping_items.items()
               if isinstance(v, dict) and v.get('label') == 'Router')
    admin._history.record('ping', key, True, {})

    _login(client)
    resp = client.get('/api/v1/history/index')
    assert resp.status_code == 200
    index = json.loads(resp.data)
    entry = next(e for e in index if e['key'] == key)
    assert entry['label'] == 'Router'


def test_index_label_falls_back_to_record_name(client, admin):
    """ram_swap emits derived keys ("<uid>_ram") that are not real item keys, so
    the label must fall back to the display 'name' stored in the record data."""
    if admin._history is None:
        return
    admin._history.record('ram_swap', 'abc123_ram', True,
                          {'used': 42.0, 'name': 'NS1 - RAM'})

    _login(client)
    resp = client.get('/api/v1/history/index')
    assert resp.status_code == 200
    index = json.loads(resp.data)
    entry = next(e for e in index if e['key'] == 'abc123_ram')
    assert entry['label'] == 'NS1 - RAM'
