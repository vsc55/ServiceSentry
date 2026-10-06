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


def test_index_groups_each_series_under_its_item(client, admin):
    """An SNMP host is twenty or thirty series under one key prefix; the index says which
    item each one hangs from, so the screen can forget them together."""
    if admin._history is None:
        return
    admin._history.record('snmp', 'host.h1/eth0', True, {})
    admin._history.record('snmp', 'srv9', True, {})
    _login(client)
    index = json.loads(client.get('/api/v1/history/index').data)
    por_clave = {e['key']: e for e in index if e['module'] == 'snmp'}
    assert por_clave['host.h1/eth0']['item'] == 'host.h1'
    assert por_clave['srv9']['item'] == 'srv9'


def test_delete_item_forgets_every_series_of_that_item_only(client, admin):
    """Reported: one item with twenty or thirty series could only be forgotten one series at
    a time. The neighbour whose key merely STARTS the same (`host.h10`) is another item."""
    if admin._history is None:
        return
    h = admin._history
    for key in ('host.h1/eth0', 'host.h1/eth1', 'host.h1/disk/C', 'host.h1', 'host.h10/eth0'):
        h.record('snmp', key, True, {})
    h.record('ping', 'host.h1/eth0', True, {})
    _login(client)
    r = client.delete('/api/v1/history/item?module=snmp&item=host.h1')
    assert r.status_code == 200
    assert json.loads(r.data)["series"] == 4
    quedan = {(e['module'], e['key']) for e in h.get_index()}
    assert ('snmp', 'host.h10/eth0') in quedan, 'otro elemento que empieza igual'
    assert ('ping', 'host.h1/eth0') in quedan, 'la misma clave en otro módulo'
    assert not any(m == 'snmp' and (k == 'host.h1' or k.startswith('host.h1/'))
                   for m, k in quedan)


def test_delete_item_needs_both_and_the_permission(client, admin):
    if admin._history is None:
        return
    _login(client)
    assert client.delete('/api/v1/history/item?module=snmp').status_code == 400
    assert client.delete('/api/v1/history/item?item=x').status_code == 400
    anon = admin.app.test_client()
    assert anon.delete('/api/v1/history/item?module=snmp&item=x').status_code in (401, 302, 403)
