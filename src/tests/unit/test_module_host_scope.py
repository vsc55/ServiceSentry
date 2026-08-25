#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry - a run that is about ONE machine.
#
"""«Obtener datos» de un dispositivo — narrowed to that dispositivo and nothing else.

A check runs for everything the module has, and for a scheduler cycle that is the right
answer: it is asking what the state of the installation is. It is the wrong answer to
"collect this device now", which is about one machine — and until now that button ran each
module with its whole configuration, so asking for one NAS walked every other device that
module watched. On an SNMP fleet that is minutes of somebody else's equipment for a number
the operator asked about one of theirs, and when one of those other devices is not answering,
it is a collection that never lands. Reported from the screen exactly that way: a dialog
stuck on "still working" listing six devices, five of which nobody had asked about.

The narrowing is applied in ONE place — `ModuleBase.get_conf` — because all twenty modules
enumerate their items the same way (`self.get_conf('list', {})`). Every test here is about
that choke point being both wide enough (every module, without any of them knowing) and
narrow enough (a module's own settings are not items, and neither is a field of one).

No Flask, no database, no device: a module is instantiated against a stand-in monitor and
asked what it can see.
"""

from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0])

from lib.modules.check_runner import ProbeMonitor          # noqa: E402

_SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]
_WATCHFULS = os.path.join(_SRC, 'watchfuls')

_ITEMS = {
    'a': {'host_uid': 'h1', 'label': 'A', 'enabled': True},
    'b': {'host_uid': 'h2', 'label': 'B', 'enabled': True},
    'c': {'label': 'bound to nothing', 'enabled': True},
}


def _watchful(module: str = 'ping', collection: str = 'list', items=None, **scalars):
    """A real module, with a real schema, over a made-up configuration."""
    if _WATCHFULS not in sys.path:
        sys.path.insert(0, os.path.dirname(_WATCHFULS))
    cfg = {f'watchfuls.{module}': {'enabled': True, **scalars,
                                   collection: dict(_ITEMS if items is None else items)}}
    mon = ProbeMonitor(cfg, None, None, modules_dir=_WATCHFULS)
    cls = importlib.import_module(f'watchfuls.{module}').Watchful
    return cls(mon)


class TestWhatANarrowedRunSees:

    def test_without_a_scope_it_sees_everything(self):
        """The scheduler's cycle and the Status screen's "run all" are asking about the
        installation, and must go on getting the whole of it."""
        w = _watchful()
        assert sorted(w.get_conf('list', {})) == ['a', 'b', 'c']
        assert w.host_scope == ''

    def test_with_one_it_sees_that_machines_items_only(self):
        w = _watchful()
        w._host_scope = 'h1'
        assert sorted(w.get_conf('list', {})) == ['a']

    def test_an_item_bound_to_nothing_is_not_this_machines(self):
        """`c` has no host. A collection of h1 that swept it in would be the button quietly
        running a check the operator did not ask about — and, worse, one whose device is
        somewhere else entirely."""
        w = _watchful()
        w._host_scope = 'h1'
        assert 'c' not in w.get_conf('list', {})

    def test_a_machine_with_nothing_bound_sees_nothing(self):
        w = _watchful()
        w._host_scope = 'nobody'
        assert w.get_conf('list', {}) == {}

    def test_the_collection_it_narrows_is_the_one_the_schema_declares(self):
        """`list` for most modules and `servers` for SNMP — read from the module's own schema.
        A name written into the core would be the core deciding a module's shape, and would be
        wrong for the twenty-first module."""
        assert _watchful()._item_collections() == {'list'}
        assert _watchful('snmp', 'servers')._item_collections() == {'servers'}

    def test_snmp_is_narrowed_by_the_same_one_line(self):
        """The module whose collection is not called `list`, which is the whole reason the
        name is read from the schema rather than assumed."""
        w = _watchful('snmp', 'servers')
        w._host_scope = 'h2'
        assert sorted(w.get_conf('servers', {})) == ['b']


class TestWhatItMustNotNarrow:
    """The scope is about ITEMS. Everything else a module reads is not one, and filtering it
    would be a narrowed run silently losing its own settings."""

    def test_a_modules_own_setting_is_not_an_item(self):
        w = _watchful(threads=7)
        w._host_scope = 'h1'
        assert w.get_conf('threads', 0) == 7

    def test_reading_one_field_of_an_item_still_works(self):
        """`['list', 'b', 'label']` is a module asking about something it has already chosen —
        and modules do read fields of items they are not iterating."""
        w = _watchful()
        w._host_scope = 'h1'
        assert w.get_conf(['list', 'b', 'label'], '') == 'B'

    def test_the_whole_module_configuration_is_not_a_collection(self):
        """`get_conf()` with no key returns the module's entire config. It is not the item
        list, so it is not filtered — and nothing may depend on it being."""
        w = _watchful()
        w._host_scope = 'h1'
        got = w.get_conf()
        assert set(got.get('list') or {}) == {'a', 'b', 'c'}

    def test_a_scope_of_only_whitespace_is_no_scope(self):
        w = _watchful()
        w._host_scope = '   '
        assert w.host_scope == ''
        assert sorted(w.get_conf('list', {})) == ['a', 'b', 'c']


class TestWhereTheScopeLives:

    def test_it_is_on_the_module_and_not_on_the_monitor(self):
        """Two runs may be in flight in one process — the scheduler's cycle and a collection
        somebody pressed a button for. A scope kept on the shared monitor would be one run
        narrowing the other's, which is a cycle that silently skips thirty-nine machines and
        then prunes them.
        """
        one, two = _watchful(), _watchful()
        one._host_scope = 'h1'
        assert sorted(two.get_conf('list', {})) == ['a', 'b', 'c']
        assert two.host_scope == ''
        assert not hasattr(one._monitor, '_host_scope')

    def test_every_module_gets_it_without_knowing_about_it(self):
        """The point of putting it in `get_conf`: no watchful mentions a scope anywhere, so
        none of them can be the one that forgot. If this stops being true, a module that
        enumerates its items some other way is polling the whole fleet on a narrowed run.
        """
        offenders = []
        for entry in sorted(os.listdir(_WATCHFULS)):
            path = os.path.join(_WATCHFULS, entry)
            if entry.startswith('_') or not os.path.isdir(path):
                continue
            for root, _dirs, files in os.walk(path):
                if 'tests' in root.split(os.sep):
                    continue
                for name in files:
                    if not name.endswith('.py'):
                        continue
                    with open(os.path.join(root, name), encoding='utf-8') as fh:
                        src = fh.read()
                    # snmp is allowed one: the devices it samples from the REGISTRY have no
                    # item to be narrowed by, so it hands the scope to `devices_to_sample`.
                    if 'host_scope' in src and entry != 'snmp':
                        offenders.append(f'{entry}/{name}')
        assert offenders == [], offenders
