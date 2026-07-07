#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the generic provisioned-host hook (`_sync_provisioned_hosts`).

Module-agnostic: the hook reads each module's ``__provision_host__`` schema
declaration and, for every item with the declared address field set, ensures a
linked host (``address == that field``) whose uid is stamped on the item's
``link_field``.  These tests drive it with a SYNTHETIC module (a temp schema
dir) so nothing here depends on any real watchful.
"""

import json
import os

import pytest

from lib.core.modules.routes import _sync_provisioned_hosts

# The synthetic module the tests declare a __provision_host__ for.
_MOD = 'demo'
_DECL = {'address_field': 'endpoint', 'link_field': 'endpoint_host_uid',
         'name_template': 'EP: {label}'}


class FakeStore:
    """Minimal in-memory HostsStore (unique names, uid generation)."""

    def __init__(self):
        self.hosts = {}
        self._n = 0

    def get(self, uid):
        return self.hosts.get(uid)

    def get_by_name(self, name):
        return next((h for h in self.hosts.values() if h['name'] == name), None)

    def create(self, data, actor=None):
        if any(h['name'] == data['name'] for h in self.hosts.values()):
            return None                      # unique-name collision
        self._n += 1
        uid = f'h{self._n}'
        self.hosts[uid] = {**data, 'uid': uid}
        return uid

    def update(self, uid, data, actor=None):
        if uid not in self.hosts:
            return False
        self.hosts[uid] = {**data, 'uid': uid}
        return True


class FakeWa:
    def __init__(self, store, modules_dir):
        self._hosts_store = store
        self._modules_dir = modules_dir


@pytest.fixture
def modules_dir(tmp_path):
    """A temp modules dir with one synthetic module declaring __provision_host__."""
    d = tmp_path / _MOD
    d.mkdir()
    (d / 'schema.json').write_text(
        json.dumps({'list': {'__provision_host__': _DECL}}), encoding='utf-8')
    return str(tmp_path)


def _data(**item):
    return {f'watchfuls.{_MOD}': {'list': {'k1': {'label': 'web', **item}}}}


def _run(store, modules_dir, data):
    _sync_provisioned_hosts(FakeWa(store, modules_dir), data, 'tester')
    return data[f'watchfuls.{_MOD}']['list']['k1']


def test_creates_and_links_host(modules_dir):
    store = FakeStore()
    item = _run(store, modules_dir, _data(endpoint='192.168.1.50'))
    uid = item['endpoint_host_uid']
    assert uid and store.get(uid)['address'] == '192.168.1.50'
    assert store.get(uid)['name'] == 'EP: web'      # name_template applied
    assert store.get(uid)['kind'] == 'local'        # no ssh profile → local


def test_idempotent(modules_dir):
    store = FakeStore()
    data = _data(endpoint='10.0.0.9')
    first = _run(store, modules_dir, data)['endpoint_host_uid']
    again = _run(store, modules_dir, data)['endpoint_host_uid']
    assert again == first
    assert len(store.hosts) == 1                     # no duplicate host


def test_syncs_address_on_change(modules_dir):
    store = FakeStore()
    data = _data(endpoint='10.0.0.9')
    uid = _run(store, modules_dir, data)['endpoint_host_uid']
    data[f'watchfuls.{_MOD}']['list']['k1']['endpoint'] = '10.0.0.10'
    _run(store, modules_dir, data)
    assert store.get(uid)['address'] == '10.0.0.10'
    assert len(store.hosts) == 1


def test_no_address_no_host(modules_dir):
    store = FakeStore()
    item = _run(store, modules_dir, _data(endpoint=''))
    assert not store.hosts
    assert 'endpoint_host_uid' not in item


def test_module_without_declaration_is_noop(tmp_path):
    """A module whose schema declares no __provision_host__ is skipped."""
    (tmp_path / 'plain').mkdir()
    (tmp_path / 'plain' / 'schema.json').write_text(
        json.dumps({'list': {'host': {'type': 'str'}}}), encoding='utf-8')
    store = FakeStore()
    _sync_provisioned_hosts(FakeWa(store, str(tmp_path)),
                            {'watchfuls.plain': {'list': {'p1': {'host': '1.1.1.1'}}}}, 't')
    assert not store.hosts


def test_adopts_existing_host_by_name(modules_dir):
    """An unlinked item adopts an existing host with the deterministic name
    instead of creating a duplicate (the anti-duplication guard)."""
    store = FakeStore()
    existing = store.create({'name': 'EP: web', 'address': 'x'}, actor='t')
    item = _run(store, modules_dir, _data(endpoint='192.168.1.50'))
    assert item['endpoint_host_uid'] == existing        # reused, not a new host
    assert len(store.hosts) == 1
    assert store.get(existing)['address'] == '192.168.1.50'   # address synced


def test_returns_assignments_for_roundtrip(modules_dir):
    """The hook returns the links it set so the caller can round-trip them; a
    re-run with the link already present returns nothing (idempotent)."""
    store = FakeStore()
    data = _data(endpoint='10.0.0.9')
    assigns = _sync_provisioned_hosts(FakeWa(store, modules_dir), data, 't')
    assert len(assigns) == 1
    a = assigns[0]
    assert a['field'] == 'endpoint_host_uid' and a['item'] == 'k1'
    assert a['uid'] == data[f'watchfuls.{_MOD}']['list']['k1']['endpoint_host_uid']
    # Link now present → a second run establishes nothing new.
    assert _sync_provisioned_hosts(FakeWa(store, modules_dir), data, 't') == []
