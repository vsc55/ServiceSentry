#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What a module says about a measurement has to reach the screen intact.

A module declares more than a label and a unit: which part of the device the value is of,
whether it is a line or a badge, what its numbers mean, how the table names its rows, whether
the profile is a standard or a vendor's own. Between the module and the browser that
declaration passes through **two whitelists** — the module projection
(``lib.modules.history_fields``) and the history metadata surface
(``lib.core.history.service.history_meta``) — and a whitelist is the right shape here: a
module must not be able to put arbitrary keys into a core structure.

The failure mode is the reason this file exists. A whitelist that does not grow drops the new
key **in silence**: no error, no warning, no log line. The value simply arrives without the
thing that said how to draw it, and the screen draws it the old way — a state as an integer, a
measurement with no heading, a table with no groups, a card in the wrong order. This has now
happened three separate times in this section, each found by somebody looking at a screen and
saying "that number means nothing".

So: whatever a module CAN declare, both whitelists must carry. Not a list written here — that
would be a fourth place to forget — but the union of what the profile machinery actually emits.
"""

from lib.core.snmp import profiles
from lib.core.history import service as history_svc
from lib.modules import history_fields as mod_fields

#: The two every field has. Everything else is optional metadata and must be whitelisted.
_ALWAYS = {'label', 'unit'}


def _richest_field() -> dict:
    """One field carrying as much metadata as a profile can attach to it.

    Built from a real profile rather than by hand: a key invented here would pass a test and
    prove nothing about what modules actually send.
    """
    prof = profiles.normalise({
        'id': 'rich', 'label': 'Rich',
        'match': {'sysobjectid_prefix': '1.3.6.1.4.1.9'},
        'row_split': '^(?P<group>[^/]+?)\\s*/\\s*(?P<row>.+)$',
        'metrics': [{
            'key': 'state', 'label': 'State', 'kind': 'gauge', 'walk': '1.2.3',
            'unit': '', 'chart': 'state',
            'states': {'1': {'label': 'Normal', 'level': 'ok'},
                       '2': {'label': 'Failed', 'level': 'bad'}},
        }],
    })
    fields = profiles.history_fields(prof, 'en_EN')
    assert 'state' in fields, 'the fixture stopped producing a field'
    return fields['state']


class TestTheModuleProjection:

    def test_every_declared_key_is_whitelisted(self):
        """`lib.modules.history_fields` copies a fixed set of keys. One it does not know is
        dropped without a word — which is what "the badge is a number again" looks like from
        the outside."""
        known = set(_ALWAYS) | set(mod_fields._OPTIONAL_META) | set(mod_fields._OPTIONAL_MAPS)
        missing = sorted(set(_richest_field()) - known)
        assert not missing, (
            f'a module can declare {missing} and the projection drops it silently — add it to '
            '_OPTIONAL_META (a word) or _OPTIONAL_MAPS (a map)')

    def test_the_whitelist_names_nothing_imaginary(self):
        """The other direction: a key in the whitelist that nothing emits is either a typo or
        a leftover, and both read as "this is handled" to the next person."""
        emitted = set(_richest_field())
        # `states` only appears on a field that HAS states; the fixture above has them, so
        # every declared key must be reachable.
        stale = sorted((set(mod_fields._OPTIONAL_META) | set(mod_fields._OPTIONAL_MAPS))
                       - emitted)
        assert not stale, f'the whitelist carries keys nothing produces: {stale}'


class TestTheHistoryMetadataSurface:

    def test_it_carries_the_same_keys(self):
        """The second whitelist, and the one the browser actually reads. The first one growing
        without this one is the same silent drop, one layer further on."""
        src = history_svc.__file__
        import io                                              # noqa: PLC0415
        text = io.open(src, encoding='utf-8').read()
        block = text.split('if k in (')[1].split(')}')[0]
        missing = [k for k in set(_richest_field()) - _ALWAYS if f"'{k}'" not in block]
        assert not missing, (
            f'history_meta does not forward {sorted(missing)} — a module declares it, the '
            'module projection keeps it, and it dies on the way to the screen')
