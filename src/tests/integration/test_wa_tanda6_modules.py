#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PUT /api/v1/modules refuses a value outside a field's declared ``options`` (WF-1/NET-1).

The dropdown in the browser bounded nothing: the save stored whatever the body carried, and
the DNS record type then reached a PowerShell command line unquoted. The check is generic,
read from every module's schema (module fields, item fields, sub-collection fields), and it
lets an ALREADY stored value through, so an old config stays saveable.
"""

import copy

import pytest

try:
    from lib.web_admin import WebAdmin  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

from tests.conftest import _login

pytestmark = pytest.mark.skipif(not _HAS_FLASK, reason="Flask is not installed")


def _current(client):
    return client.get('/api/v1/modules').get_json()


def _put(client, data):
    return client.put('/api/v1/modules', json=data)


def _with(client, module, cfg):
    data = copy.deepcopy(_current(client))
    data[module] = cfg
    return data


class TestClosedOptions:

    def test_dns_record_type_injection_is_refused(self, client, admin):
        _login(client)
        data = _with(client, 'dns', {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'example.test', 'record_type': 'A;calc'}}})
        resp = _put(client, data)
        assert resp.status_code == 400
        assert 'record_type' in resp.get_json()['error']
        assert 'dns' not in _current(client)            # nothing was stored

    def test_a_listed_value_saves(self, client):
        _login(client)
        data = _with(client, 'dns', {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'example.test', 'record_type': 'MX'}}})
        assert _put(client, data).status_code == 200

    def test_blank_means_the_default_and_saves(self, client):
        _login(client)
        data = _with(client, 'dns', {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'example.test', 'record_type': ''}}})
        assert _put(client, data).status_code == 200

    def test_module_level_field_is_checked(self, client):
        _login(client)
        data = _with(client, 'm365', {'enabled': True, 'site_free_unit': 'XB', 'list': {}})
        assert _put(client, data).status_code == 400

    def test_sub_collection_field_is_checked(self, client):
        _login(client)
        data = _with(client, 'snmp', {'enabled': True, 'servers': {'s1': {
            'enabled': True, 'host': '192.0.2.1', 'checks': {
                'k1': {'enabled': True, 'oid': '1.3.6.1.2.1.1.1.0', 'operator': 'evil'}}}}})
        assert _put(client, data).status_code == 400

    def test_core_profile_field_is_checked(self, client):
        """`version` arrives in the SNMP collection from the core SNMP profile."""
        _login(client)
        data = _with(client, 'snmp', {'enabled': True, 'servers': {'s1': {
            'enabled': True, 'host': '192.0.2.1', 'version': '4'}}})
        assert _put(client, data).status_code == 400

    def test_free_text_fields_are_untouched(self, client):
        _login(client)
        data = _with(client, 'dns', {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'any; text $(here)', 'record_type': 'A',
                   'expected': 'whatever "you" like'}}})
        assert _put(client, data).status_code == 200


class TestStoredValuesStaySaveable:

    def test_legacy_value_already_stored_passes(self, client, admin):
        stored = copy.deepcopy(_current_raw(admin))
        stored['dns'] = {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'example.test', 'record_type': 'a'}}}
        admin._save_modules(stored)
        _login(client)
        data = _current(client)
        data['dns']['list']['c1']['host'] = 'other.example.test'   # touch another field
        assert _put(client, data).status_code == 200

    def test_changing_to_another_bad_value_is_refused(self, client, admin):
        stored = copy.deepcopy(_current_raw(admin))
        stored['dns'] = {'enabled': True, 'list': {
            'c1': {'enabled': True, 'host': 'example.test', 'record_type': 'a'}}}
        admin._save_modules(stored)
        _login(client)
        data = _current(client)
        data['dns']['list']['c1']['record_type'] = 'A|calc'
        assert _put(client, data).status_code == 400


def _current_raw(admin):
    from lib.core.modules import facade
    data, _version = facade.snapshot(admin)
    return data


class TestClosedOptionsUnit:
    """The validator on its own, for the shapes the HTTP tests do not reach."""

    def test_dict_options_and_lists(self):
        from lib.core.modules.service import validate_option_values
        from lib.core.users.service import AdminOpError
        schemas = {'m|list': {'f': {'type': 'str', 'options': [{'value': 'x'}, {'value': 'y'}]},
                              'g': {'type': 'str', 'options': ['a', 'b'], 'allow_custom': True}}}
        validate_option_values({'m': {'list': {'i': {'f': 'y', 'g': 'zzz'}}}}, {}, schemas)
        validate_option_values({'m': {'list': {'i': {'f': ['x', 'y']}}}}, {}, schemas)
        with pytest.raises(AdminOpError):
            validate_option_values({'m': {'list': {'i': {'f': ['x', 'q']}}}}, {}, schemas)
        with pytest.raises(AdminOpError):
            validate_option_values({'m': {'list': {'i': {'f': {'x': 1}}}}}, {}, schemas)

    def test_watchfuls_prefixed_module_key(self):
        from lib.core.modules.service import validate_option_values
        from lib.core.users.service import AdminOpError
        schemas = {'dns|list': {'record_type': {'type': 'str', 'options': ['A']}}}
        with pytest.raises(AdminOpError):
            validate_option_values(
                {'watchfuls.dns': {'list': {'i': {'record_type': 'B'}}}}, {}, schemas)
