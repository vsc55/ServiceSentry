#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The SNMP connection is described once, and this is what checks that it arrives.

``lib/core/snmp/manifest.py`` declares the profile a HOST carries: what the Servers form
draws, and what any check bound to that host inherits. A check against a bare IP has to stay
possible without registering a device first, so the same fields have to appear on a *server*
item too — and the module used to write them out a second time for that.

It does not any more: the collection names the protocol (``"__profile_fields__": "snmp"``)
and the panel expands it into the real declarations from the core one. So these no longer pin
a copy against an original; they pin the EXPANSION, which is what can now fail quietly. If it
stopped delivering, the loose-IP form would lose its community box and its v3 keys and
nothing would raise — the form would simply be shorter, and a check against a bare address
would have no way left to authenticate.
"""

import io
import json
import os

from lib.core.hosts.resolve import host_profile_specs

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
SCHEMA = os.path.join(SRC, 'watchfuls', 'snmp', 'schema.json')

# What has to match, field by field. `placeholder` is deliberately not here: it is a hint for
# an empty box and the two forms are within their rights to word it differently.
_META = ('type', 'default', 'options', 'show_when', 'secret', 'multi', 'min', 'max')


def _schema():
    with io.open(SCHEMA, encoding='utf-8') as fh:
        return json.load(fh)


def _servers():
    """The ``servers`` collection AS THE BROWSER GETS IT — expanded, i18n merged."""
    from lib.modules import ModuleBase                        # noqa: PLC0415
    return ModuleBase.discover_schemas()['snmp|servers']


def _core():
    from lib.core.snmp.manifest import HOST_PROFILE          # noqa: PLC0415
    return {f['name']: f for f in HOST_PROFILE['fields']}


class TestTheTwoDescriptionsAgree:

    def test_every_core_field_exists_on_the_check(self):
        """An inline check has to be able to say everything a host can say, or the loose-IP
        case is a second-class citizen that quietly cannot do SNMPv3."""
        servers = _servers()
        missing = [n for n in _core() if n not in servers]
        assert not missing, f'the check cannot express: {missing}'

    def test_the_check_does_not_restate_them(self):
        """The positive control for the one above. Without it the expansion could stop
        working and the assertion would go green again the moment somebody "fixed" the empty
        form by pasting the ten fields back into schema.json — which is where they were."""
        servers = _schema()['servers']
        assert servers.get('__profile_fields__') == 'snmp'
        restated = [n for n in _core() if n in servers]
        assert not restated, f'written down twice again: {restated}'

    def test_the_metadata_matches_field_by_field(self):
        servers = _servers()
        bad = []
        for name, core_f in _core().items():
            mod_f = servers.get(name) or {}
            for key in _META:
                a, b = core_f.get(key), mod_f.get(key)
                if a != b:
                    bad.append(f'{name}.{key}: core={a!r} schema={b!r}')
        assert not bad, 'the two descriptions have drifted:\n  ' + '\n  '.join(bad)

    def test_the_module_names_the_protocol_and_the_core_says_what_it_holds(self):
        """The module keeps its ``__host_profile__`` — that is what makes a check bound to a
        host inherit these fields — but it no longer RESTATES them. It used to, and so did
        ten other modules for SSH; the list is not theirs to hold.

        What the module still says is where the address lands: which field of ITS item
        receives it is genuinely its own business (``web`` puts it in ``server``)."""
        hp = _schema().get('__host_profile__') or {}
        assert hp.get('key') == 'snmp'
        assert hp.get('address_field') == 'host'
        assert 'fields' not in hp, 'the module is restating a list the core owns'
        [spec] = host_profile_specs(hp)
        assert set(spec['fields']) == set(_core())

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


class TestTheCredentialSaysTheSameThing:
    """A third description of the same connection, and the one with a lock on it.

    A credential is what a device answers to, reused across as many hosts as you like. It was
    declared by the SNMP watchful, which an installation may not have — and a credential type
    that disappears takes its stored credentials out of the editor while they stay in the
    database, still referenced by the hosts that use them.

    Declared by the core now, and pinned against the host profile because the two describe
    the same fields: a `show_when` that drifts hides a v3 key on one form and not the other,
    and an `options` list that drifts offers an auth protocol the other cannot store.
    """

    @staticmethod
    def _cred():
        from lib.core.snmp.manifest import CREDENTIAL      # noqa: PLC0415
        return {f['name']: f for f in CREDENTIAL['fields']}

    def test_it_is_declared_by_the_core_and_reaches_the_catalogue(self):
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        cat = credential_schemas()
        assert 'snmp_auth' in cat, 'the SNMP credential type is gone from the editor'
        # `module` still says 'snmp': it is what the host form reads to offer this type on
        # the SNMP profile's card, and that is a lookup key, not a claim about who ran it.
        assert cat['snmp_auth']['module'] == 'snmp'
        assert len(cat['snmp_auth']['fields']) == len(self._cred())

    def test_the_identity_fields_agree_with_the_host_profile(self):
        core = _core()
        cred = self._cred()
        shared = sorted(set(core) & set(cred))
        assert 'community' in shared and 'version' in shared, shared
        bad = []
        for name in shared:
            for key in ('secret', 'options'):
                a, b = core[name].get(key), cred[name].get(key)
                # The credential's v3 options are the ones it can STORE; the profile also
                # offers 'none' because an inline check may say "no auth protocol at all".
                if key == 'options' and a and b and set(b) <= set(a):
                    continue
                if a != b:
                    bad.append(f'{name}.{key}: profile={a!r} credential={b!r}')
        assert not bad, 'the two descriptions have drifted:\n  ' + '\n  '.join(bad)

    def test_every_credential_field_is_worded_in_both_languages(self):
        """A missing label puts the raw field name in the credential editor, which is the
        one screen where somebody is typing a secret and needs to know into what."""
        from lib.core.snmp.manifest import CREDENTIAL      # noqa: PLC0415
        from lib.i18n import TRANSLATIONS                  # noqa: PLC0415
        section = CREDENTIAL['i18n']
        for lang in ('es_ES', 'en_EN'):
            words = (TRANSLATIONS.get(lang) or {}).get(section) or {}
            assert words.get('type'), f'the credential type has no name in {lang}'
            missing = [n for n in self._cred() if not (words.get('labels') or {}).get(n)]
            assert not missing, f'{lang} has no label for {missing}'


class TestTheCredentialTheEditorActuallyGETS:
    """The catalogue, not the declaration: what ``credential_schemas()`` hands the editor.

    These lived in the SNMP watchful's own test file, testing a declaration the watchful no
    longer makes — so the guard on a core credential type would have been removed along with
    the module, and what it guards is a form where somebody types a device password.

    Which fields apply depends on the version, and on v3 also on the security level; that
    conditional is the whole reason the type has a schema instead of a fixed form.
    """

    @staticmethod
    def _fields():
        from lib.modules.discovery.credential_schemas import credential_schemas  # noqa: PLC0415
        cat = credential_schemas()
        assert 'snmp_auth' in cat, 'the SNMP credential type is gone from the editor'
        return {f['name']: f for f in cat['snmp_auth']['fields']}

    def test_v1_and_v2c_ask_only_for_the_community(self):
        """Everything else on the form belongs to v3, and a form that offers a user name for
        a v2c device is asking for something that has nowhere to go."""
        f = self._fields()
        assert f['community']['show_when'] == {'version': ['1', '2c']}
        for name in ('snmpv3_username', 'snmpv3_level', 'snmpv3_context'):
            assert f[name]['show_when']['version'] == ['3']

    def test_the_keys_follow_the_security_level_not_only_the_version(self):
        """noAuthNoPriv needs neither key, authNoPriv needs one, authPriv both. Gating them on
        the version alone would show two key boxes that the device will ignore — and a filled
        box that does nothing is worse than an absent one, because it looks configured."""
        f = self._fields()
        for name in ('snmpv3_auth_protocol', 'snmpv3_auth_key'):
            assert f[name]['show_when'] == {'version': ['3'],
                                            'snmpv3_level': ['authNoPriv', 'authPriv']}
        for name in ('snmpv3_priv_protocol', 'snmpv3_priv_key'):
            assert f[name]['show_when'] == {'version': ['3'], 'snmpv3_level': ['authPriv']}

    def test_every_secret_is_marked_as_one(self):
        """`secret` is what encrypts the value at rest and masks it in the API. A key that
        misses it is stored in clear and returned in clear."""
        f = self._fields()
        for name in ('community', 'snmpv3_auth_key', 'snmpv3_priv_key'):
            assert f[name]['secret'] is True, f'{name} is stored in the clear'
        assert f['snmpv3_username']['secret'] is False, 'a user name is not a secret'

    def test_the_protocol_lists_dropped_none(self):
        """The check's lists carry a "none" option because they have no level field: it is
        how they say authNoPriv. Here the level says it, and two places to say the same thing
        is two places to disagree."""
        f = self._fields()
        for name in ('snmpv3_auth_protocol', 'snmpv3_priv_protocol'):
            values = [o.get('value') if isinstance(o, dict) else o for o in f[name]['options']]
            assert 'none' not in values, f'{name} says authNoPriv a second way'

    def test_the_security_level_is_offered_in_words(self):
        """`noAuthNoPriv` is not English — the three values are ASN.1 identifiers out of the
        USM MIB, and a picker offering them raw asks the operator to know the standard to
        answer what the session should protect.

        Worth pinning rather than assuming: the wording lived in the module's lang file, and
        moving the declaration to the core left it behind. Nothing failed. The picker simply
        started showing the identifiers, in both languages, on the credential form.
        """
        opts = self._fields()['snmpv3_level']['options']
        for opt in opts:
            assert isinstance(opt, dict), f'{opt!r} reaches the form as a bare identifier'
            for lang in ('es_ES', 'en_EN'):
                assert (opt.get('label_i18n') or {}).get(lang),                     f"{opt['value']} has no {lang} wording"
