#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The SNMP connection is described twice, and the two must not drift.

``lib/core/snmp/manifest.py`` declares the profile a HOST carries: what the Servers form
draws, and what any check bound to that host inherits. ``watchfuls/snmp/schema.json``
declares the same fields on a *server* item, because a check against a bare IP has to stay
possible without registering a device first.

Neither can be derived from the other. The core one is Python that binds live metadata and is
read before any module is loaded; the module one is data the browser renders. So they are
written out twice, and this is what stops that from being a bug in waiting: a `show_when` that
drifts hides a field on one screen and not the other, an `options` list that drifts offers an
auth protocol the check cannot use, and a `secret` flag that drifts stops encrypting a
password — none of which raises anything anywhere.
"""

import io
import json
import os

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
SCHEMA = os.path.join(SRC, 'watchfuls', 'snmp', 'schema.json')

# What has to match, field by field. `placeholder` is deliberately not here: it is a hint for
# an empty box and the two forms are within their rights to word it differently.
_META = ('type', 'default', 'options', 'show_when', 'secret', 'multi', 'min', 'max')


def _schema():
    with io.open(SCHEMA, encoding='utf-8') as fh:
        return json.load(fh)


def _core():
    from lib.core.snmp.manifest import HOST_PROFILE          # noqa: PLC0415
    return {f['name']: f for f in HOST_PROFILE['fields']}


class TestTheTwoDescriptionsAgree:

    def test_every_core_field_exists_on_the_check(self):
        """An inline check has to be able to say everything a host can say, or the loose-IP
        case is a second-class citizen that quietly cannot do SNMPv3."""
        servers = _schema()['servers']
        missing = [n for n in _core() if n not in servers]
        assert not missing, f'the check cannot express: {missing}'

    def test_the_metadata_matches_field_by_field(self):
        servers = _schema()['servers']
        bad = []
        for name, core_f in _core().items():
            mod_f = servers.get(name) or {}
            for key in _META:
                a, b = core_f.get(key), mod_f.get(key)
                if a != b:
                    bad.append(f'{name}.{key}: core={a!r} schema={b!r}')
        assert not bad, 'the two descriptions have drifted:\n  ' + '\n  '.join(bad)

    def test_the_module_still_inherits_them_when_bound(self):
        """The module keeps its own ``__host_profile__``: that is the declaration that makes
        a check bound to a host inherit these fields instead of restating them."""
        hp = _schema().get('__host_profile__') or {}
        assert hp.get('key') == 'snmp'
        assert set(hp.get('fields') or []) == set(_core())

    def test_the_core_declaration_is_the_one_the_form_draws(self):
        """Declared by a core package and picked up by the shared scanner, so the catalogue
        offers it whether or not the watchful is installed — which is the whole point."""
        from lib.core.hosts.profiles import host_profiles_catalog   # noqa: PLC0415
        entry = host_profiles_catalog()['snmp']
        assert entry.get('builtin') is True
        assert entry['address_field'] == 'host'
        assert [f['name'] for f in entry['fields']] == list(_core())

    def test_every_field_is_named_in_both_languages(self):
        """A core-owned form takes its words from core i18n; a missing one puts the raw field
        name on screen, which is only ever noticed by looking at the page."""
        from lib.i18n import TRANSLATIONS                            # noqa: PLC0415
        for lang in ('es_ES', 'en_EN'):
            labels = ((TRANSLATIONS.get(lang) or {}).get('snmp_profile') or {}).get('labels') or {}
            missing = [n for n in _core() if not labels.get(n)]
            assert not missing, f'{lang} has no label for {missing}'
