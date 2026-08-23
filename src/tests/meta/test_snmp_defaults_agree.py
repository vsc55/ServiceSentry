#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The duplication this file used to pin is gone. This is what replaced it.

Port 161, community "public", version 2c: the SNMP connection defaults used to exist twice,
because the two readers could not read the same thing. ``lib/core/snmp/defaults.py`` is what
CODE reads when a server leaves a field unset — the scheduler, the test screen, discovery.
``watchfuls/snmp/schema.json`` was what the BROWSER read to render the form, and a schema is
data: it cannot call a Python constant.

It does not have to any more. The collection names the protocol (``"__profile_fields__":
"snmp"``) and the panel expands the core declaration into it before the browser ever sees it,
so the form now renders the same constant the scheduler obeys.

Which moves the failure rather than removing it. The old one was drift — change the core
default and the form still offers the old one. The new one is **absence**: if the expansion
stops delivering, no default reaches the form at all, and nothing raises. The module's own
file is where that bites hardest — ``watchfuls/snmp/defaults.py`` reads schema.json straight
off disk, with no expansion, so it has to take the connection half from the core explicitly.
"""

import io
import json
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
SCHEMA = os.path.join(SRC, 'watchfuls', 'snmp', 'schema.json')


def _raw_servers():
    """``servers`` as written — no expansion. What the module's own code reads."""
    with io.open(SCHEMA, encoding='utf-8') as fh:
        return json.load(fh)['servers']


def _rendered_servers():
    """``servers`` as the browser gets it — expanded."""
    from lib.modules import ModuleBase                        # noqa: PLC0415
    return ModuleBase.discover_schemas()['snmp|servers']


class TestTheFormOffersTheDefaultTheSchedulerObeys:

    def test_every_core_default_reaches_the_form(self):
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        servers = _rendered_servers()
        for field, value in CONN_DEFAULTS.items():
            assert field in servers, f'{field} is a core default with no field on the form'
            assert servers[field].get('default') == value, (
                f'{field}: core says {value!r}, the form offers '
                f'{servers[field].get("default")!r}')

    def test_the_expansion_is_what_puts_them_there(self):
        """The positive control. Six of the seven are not in schema.json at all now, so
        without this the test above could be reading a copy somebody pasted back."""
        raw = _raw_servers()
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        assert raw.get('__profile_fields__') == 'snmp'
        restated = sorted(set(CONN_DEFAULTS) & set(raw) - {'timeout', 'retries'})
        assert not restated, f'the schema states these again: {restated}'

    def test_the_core_covers_what_opening_a_connection_needs(self):
        """Not every schema field — the check's own settings are not the protocol's — but
        the ones without which you cannot start a conversation at all."""
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        assert {'port', 'version', 'community'} <= set(CONN_DEFAULTS)

    def test_what_the_check_decides_for_itself_is_not_in_it(self):
        """Whether an entry is switched on, and what the device declares itself to be, are
        not answers the protocol has. ``timeout`` and ``retries`` ARE in both, deliberately —
        how long to wait is a property of the path to a device — and that overlap is the one
        pair still written down twice, which the test below is for."""
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        assert 'enabled' not in CONN_DEFAULTS
        assert 'device_profiles' not in CONN_DEFAULTS


class TestTheOnePairStillWrittenTwice:
    """``timeout`` and ``retries`` stay on the check because the host profile has no place
    for them: a slow device cannot yet carry its own patience, so each check states it. The
    core states them too, for the callers that never see a check — discovery, the test
    screen. Two places, one meaning, no mechanism between them."""

    def test_they_agree(self):
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        raw = _raw_servers()
        for field in ('timeout', 'retries'):
            assert field in raw, f'{field} left the schema — is it host-owned now?'
            assert raw[field].get('default') == CONN_DEFAULTS[field], (
                f'{field}: core says {CONN_DEFAULTS[field]!r}, the check offers '
                f'{raw[field].get("default")!r}')

    def test_the_modules_own_defaults_carry_the_connection_too(self):
        """``watchfuls/snmp/defaults.py`` parses schema.json itself, so the expansion never
        touches what it reads. Left to the schema alone it would have lost port, version and
        community in silence — and a server that never set a port would have been asked on
        whatever ``int('')`` raised."""
        from lib.core.snmp.defaults import CONN_DEFAULTS      # noqa: PLC0415
        from watchfuls.snmp.defaults import _SERVER_DEFAULTS  # noqa: PLC0415
        for field, value in CONN_DEFAULTS.items():
            assert _SERVER_DEFAULTS.get(field) == value, f'{field} is not what the core says'
        assert _SERVER_DEFAULTS.get('enabled') is True, 'the schema half went missing'
