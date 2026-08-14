#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where a module action gets its address and its identity from.

An action posted as one flat form carries ``host_uid`` and ``cred_uid`` at the top level, and
the route resolves them there.  A discovery scoped to a parent item is a different shape: the
UI posts ``{module scalars…, "<collection>": {"<key>": {…the item…}}}``, and the item is where
those two keys live.

Resolving only the top level handed the action an item with an empty address and no identity.
Reported as "you launch OID discovery against a server and get nothing back": the SNMP server
took its address from a bound host and its community from a credential, so `discover` saw
``host: ''`` and skipped it before sending a packet — while the checks on that same server ran
fine, because the check path resolves per item and this one did not. Nothing said so; an empty
result reads as "this device has no OIDs".

Flask-free: the resolution is dicts in, dicts out.
"""

import pytest

from lib.core.modules.actions import apply_item_identities


class _Hosts:
    def __init__(self, rows):
        self._rows = rows

    def get(self, uid, decrypt=False):
        return self._rows.get(uid)


class _Creds:
    def __init__(self, rows):
        self._rows = rows

    def get(self, uid):
        return self._rows.get(uid)


class _WA:
    _modules_dir = ''

    def __init__(self, hosts=None, creds=None):
        self._hosts_store = _Hosts(hosts or {})
        self._credentials_store = _Creds(creds or {})


HOST = {'h1': {'uid': 'h1', 'address': 'pve01.example.lan', 'kind': 'remote',
               'os': 'linux', 'profiles': {}}}
CRED = {'c1': {'enabled': True, 'data': {'version': '2c', 'community': 's3cret'}}}


@pytest.fixture
def wa():
    return _WA(HOST, CRED)


class TestAnItemBringsItsOwnIdentity:

    def test_the_credential_reaches_the_item(self, wa):
        cfg = {'servers': {'PVE01': {'cred_uid': 'c1', 'port': 161}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01']['community'] == 's3cret'
        assert cfg['servers']['PVE01']['version'] == '2c'

    def test_the_credential_wins_over_the_items_own_value(self, wa):
        """The rule the top-level pass already follows — "overlay it last so it wins" — and the
        two must not differ: an action that authenticated one way when posted as a form and
        another when posted as an item would be the harder bug of the two to see.

        The item keeps whatever the credential does not speak for (a blank field there is not
        an answer), which is why the address filled from the bound host survives below."""
        cfg = {'servers': {'PVE01': {'cred_uid': 'c1', 'version': '3', 'port': 1610}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01']['version'] == '2c'
        assert cfg['servers']['PVE01']['port'] == 1610

    def test_the_bound_host_fills_an_empty_address(self, wa):
        """The case it was reported from: the server's own `host` is blank because the address
        comes from the host it is bound to."""
        cfg = {'servers': {'PVE01': {'host_uid': 'h1', 'host': '', 'cred_uid': 'c1'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01']['host'] == 'pve01.example.lan'

    def test_an_address_typed_on_the_item_beats_the_bound_host(self, wa):
        """The host FILLS, it does not overrule: a per-check override is the reason that field
        stays editable on a bound item."""
        cfg = {'servers': {'PVE01': {'host_uid': 'h1', 'host': '10.0.0.9'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01']['host'] == '10.0.0.9'

    def test_an_item_without_either_is_left_alone(self, wa):
        cfg = {'servers': {'PVE01': {'host': '10.0.0.1', 'version': '2c'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01'] == {'host': '10.0.0.1', 'version': '2c'}

    def test_module_scalars_are_not_mistaken_for_a_collection(self, wa):
        """The posted body carries the module's own fields beside the collection."""
        cfg = {'enabled': True, 'threads': 5, 'mib_dirs': '',
               'servers': {'PVE01': {'cred_uid': 'c1'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['enabled'] is True and cfg['threads'] == 5
        assert cfg['servers']['PVE01']['community'] == 's3cret'

    def test_a_dunder_key_is_never_walked(self, wa):
        """`__host__` and `__connector__` are injected by the route and are not items."""
        cfg = {'__host__': {'address': 'x'}, 'servers': {'PVE01': {'cred_uid': 'c1'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['__host__'] == {'address': 'x'}

    def test_a_disabled_credential_supplies_nothing(self, wa):
        wa._credentials_store = _Creds({'c1': {'enabled': False,
                                               'data': {'community': 'old'}}})
        cfg = {'servers': {'PVE01': {'cred_uid': 'c1'}}}
        apply_item_identities(wa, 'snmp', cfg)
        assert 'community' not in cfg['servers']['PVE01']

    def test_a_missing_store_is_not_an_error(self):
        """A slimmed process may have neither store. Raising here would turn every action on
        a host-bound item into a 500."""
        cfg = {'servers': {'PVE01': {'cred_uid': 'c1', 'host_uid': 'h1'}}}
        wa = _WA()
        wa._hosts_store = None
        wa._credentials_store = None
        apply_item_identities(wa, 'snmp', cfg)
        assert cfg['servers']['PVE01']['cred_uid'] == 'c1'
