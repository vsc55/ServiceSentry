#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One duplication, pinned.

The SNMP connection defaults exist twice on purpose, and the reason is that the two readers
cannot read the same thing. ``lib/core/snmp/defaults.py`` is what CODE reads when a server
leaves a field unset — the scheduler, the test screen, discovery. ``watchfuls/snmp/schema.json``
is what the BROWSER reads to render the form: a schema is data, and data cannot call a Python
constant.

So they are written out twice, and the failure that follows is the quiet kind. Change the core
default for ``timeout`` and the form still offers the old one as the placeholder; change the
schema and a check that leaves the field blank still uses the old one. Nothing raises, nothing
logs, and the number on screen is simply not the number in use.

This is the guard that makes the duplication safe rather than merely deliberate.
"""

import io
import json
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
SCHEMA = os.path.join(SRC, 'watchfuls', 'snmp', 'schema.json')


def _schema_servers():
    with io.open(SCHEMA, encoding='utf-8') as fh:
        return json.load(fh)['servers']


class TestTheTwoCopiesAgree:

    def test_every_core_default_is_the_schema_s_default(self):
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        servers = _schema_servers()
        for field, value in CONN_DEFAULTS.items():
            assert field in servers, f'{field} is a core default with no schema field'
            assert servers[field].get('default') == value, (
                f'{field}: core says {value!r}, the form offers '
                f'{servers[field].get("default")!r}')

    def test_the_core_covers_what_opening_a_connection_needs(self):
        """Not every schema field — the check's own settings are not the protocol's — but
        the ones without which you cannot start a conversation at all."""
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        assert {'port', 'version', 'community'} <= set(CONN_DEFAULTS)

    def test_the_check_s_own_settings_are_not_in_it(self):
        """`timeout` and `retries` are how long we wait before giving up, which is a policy
        the check holds — they are deliberately NOT host-owned either (see the host profile),
        and putting them here would make the core the third place that has an opinion."""
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        assert 'enabled' not in CONN_DEFAULTS
        assert 'device_profiles' not in CONN_DEFAULTS

    def test_the_schema_is_where_the_form_reads_it(self):
        """A positive control for the pairing above: if the schema ever stopped declaring
        defaults, every assertion here would pass by comparing nothing."""
        servers = _schema_servers()
        declared = [k for k, v in servers.items()
                    if isinstance(v, dict) and 'default' in v]
        assert len(declared) >= 8, f'the schema declares only {declared}'
