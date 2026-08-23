#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A protocol the core owns says what its fields are — in one place.

Eleven modules used to restate that list in their ``__host_profile__``: ten repeating the
same seven SSH names, and SNMP the ten of its own — eighty names in all. The catalogue already ignored every copy —
a core-declared profile overrides a module-declared one — so a copy that drifted did not
change the form anybody sees. It changed something quieter: ``resolve_host`` reads that list
to decide **which values a bound host may push onto the check**, and the hide-when-bound list
reads it to decide what a bound check stops drawing.

They had drifted. All ten listed ``ssh_host`` and none listed ``ssh_auth_method``, so a
host that stored its authentication method without a named credential never handed it over.
Nothing failed; the check just authenticated the default way.

This is what stops the copies from coming back.
"""

import io
import json
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
WATCHFULS = os.path.join(SRC, 'watchfuls')


def _schemas():
    """``{module: schema}`` for every watchful that declares a host profile."""
    out = {}
    for entry in sorted(os.listdir(WATCHFULS)):
        path = os.path.join(WATCHFULS, entry, 'schema.json')
        if entry.startswith('_') or not os.path.isfile(path):
            continue
        with io.open(path, encoding='utf-8') as fh:
            schema = json.load(fh)
        if schema.get('__host_profile__'):
            out[entry] = schema
    return out


def _raw_specs(schema):
    hp = schema['__host_profile__']
    return [hp] if isinstance(hp, dict) else [s for s in hp if isinstance(s, dict)]


class TestNobodyRestatesWhatTheCoreOwns:

    def test_no_module_lists_the_fields_of_a_core_owned_protocol(self):
        from lib.core.hosts.profiles import core_profile_field_names   # noqa: PLC0415
        guilty = []
        for mod, schema in _schemas().items():
            for spec in _raw_specs(schema):
                if spec.get('fields') and core_profile_field_names(spec.get('key')):
                    guilty.append(f"{mod} restates {spec['key']}")
        assert not guilty, ('a list the core owns, written down again:\n  '
                            + '\n  '.join(guilty))

    def test_a_module_that_binds_to_one_still_resolves_to_its_fields(self):
        """Deleting the copies is only safe because normalising a spec fills them in. If it
        stopped, every one of these modules would bind to a host and inherit nothing — and
        the check would fall back to its inline (blank) connection rather than fail."""
        from lib.core.hosts.profiles import core_profile_field_names   # noqa: PLC0415
        from lib.core.hosts.resolve import host_profile_specs          # noqa: PLC0415
        seen = 0
        for mod, schema in _schemas().items():
            for spec in host_profile_specs(schema['__host_profile__']):
                names = core_profile_field_names(spec.get('key'))
                if not names:
                    continue
                seen += 1
                assert set(names) <= set(spec.get('fields') or []), \
                    f"{mod} inherits nothing for {spec['key']}"
        assert seen >= 11, f'only {seen} bindings to a core protocol — did they move?'


class TestTheAddressFieldIsHostOwned:

    def test_it_is_in_the_list_a_bound_check_stops_drawing(self):
        """It is the field that RECEIVES the host's address. ``datastore`` has a real
        ``ssh_host`` box on its items, so leaving it out puts that box back on a check that
        is already bound — asking for an address the host has already given."""
        from lib.core.hosts.profiles import (core_profile_field_names,   # noqa: PLC0415
                                             module_host_fields)
        hidden = module_host_fields()
        for mod, schema in _schemas().items():
            for spec in _raw_specs(schema):
                addr = str(spec.get('address_field') or '').strip()
                if not addr or not core_profile_field_names(spec.get('key')):
                    continue
                assert addr in (hidden.get(mod) or []), \
                    f'{mod} would draw {addr} on a bound check'

    def test_a_visible_address_on_a_module_owned_protocol_stays_visible(self):
        """``web`` binds to ``http``, which the core does not own, and its ``server`` box is
        deliberately editable: one host behind a reverse proxy serves several FQDNs."""
        from lib.core.hosts.profiles import module_host_fields          # noqa: PLC0415
        assert 'server' not in (module_host_fields().get('web') or [])
