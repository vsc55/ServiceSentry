#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""History fields a module works out at run time.

What a module charts is declared in its ``schema.json``, which is right while the answer is the
same on every install. It stops being right the moment the answer depends on data the
installation supplies: the SNMP watchful records whatever its device profiles declare, and one
of those profiles was written for the box in somebody's rack after this release shipped. A
schema cannot name a field that did not exist when it was written.

So a module may also declare them at run time. Two properties matter more than the mechanism:

* **the static declaration wins.** It is the one somebody wrote down on purpose, and a run-time
  discovery that silently renamed it would turn the schema into a lie that reads as correct;
* **failure is an empty map, never an exception.** These names decide what a chart's legend
  says. A module that cannot answer costs its own labels — the values are still recorded and
  still charted, read as their raw field names — and that is not a reason for the History page
  to return a 500.
"""

import os
import sys
import types

import pytest

from lib.modules.history_fields import module_history_fields

SRC = os.path.abspath(__file__).split(os.sep + 'tests' + os.sep)[0]


@pytest.fixture
def fake_module():
    """Install a throwaway ``watchfuls.<name>`` for one test and take it away after."""
    made: list = []

    def _make(name, hook):
        mod = types.ModuleType(f'watchfuls.{name}')
        if hook is not None:
            mod.discover_history_fields = hook
        sys.modules[f'watchfuls.{name}'] = mod
        made.append(f'watchfuls.{name}')
        return mod

    yield _make
    for key in made:
        sys.modules.pop(key, None)


class TestWhatAModuleCanDeclare:

    def test_a_module_that_declares_nothing_is_not_an_error(self, fake_module):
        """Nineteen of the twenty-one watchfuls have no reason to grow this hook."""
        fake_module('quiet', None)
        assert module_history_fields('quiet') == {}

    def test_the_fields_come_back_as_the_history_speaks_them(self, fake_module):
        fake_module('talkative', lambda lang, var_dir='': {
            'cpu_user': {'label': 'CPU user', 'unit': '%'}})
        assert module_history_fields('talkative', 'es_ES') == {
            'cpu_user': {'label': 'CPU user', 'unit': '%'}}

    def test_a_field_with_no_label_is_still_a_field(self, fake_module):
        """A metric nobody translated is charted under its own name, which is a worse legend
        and a working one."""
        fake_module('bare', lambda lang, var_dir='': {'load1': {}})
        assert module_history_fields('bare') == {'load1': {'label': 'load1', 'unit': ''}}

    def test_the_reader_language_and_the_data_directory_are_passed_through(self, fake_module):
        """The labels are translated, and the installation's own profiles live under the data
        directory — a hook that never saw it could only ever describe what shipped."""
        seen = {}

        def hook(lang, var_dir=''):
            seen['lang'], seen['var_dir'] = lang, var_dir
            return {}

        fake_module('curious', hook)
        module_history_fields('curious', 'es_ES', '/var/lib/servicesentry')
        assert seen == {'lang': 'es_ES', 'var_dir': '/var/lib/servicesentry'}

    def test_a_hook_that_only_cares_about_the_language_still_works(self, fake_module):
        """The data directory is the second thing this grew; a module that does not need it
        should not have to accept it."""
        fake_module('simple', lambda lang: {'x': {'label': 'X'}})
        assert 'x' in module_history_fields('simple', 'en_EN', '/var')


class TestNothingHereCanBreakAChart:

    def test_a_hook_that_raises_costs_its_own_labels(self, fake_module):
        def boom(lang, var_dir=''):
            raise RuntimeError('the profile folder is on fire')

        fake_module('broken', boom)
        assert module_history_fields('broken') == {}

    def test_a_hook_that_returns_junk_is_ignored(self, fake_module):
        fake_module('confused', lambda lang, var_dir='': ['cpu', 'ram'])
        assert module_history_fields('confused') == {}

    def test_a_field_that_is_not_a_map_is_taken_at_its_name(self, fake_module):
        fake_module('loose', lambda lang, var_dir='': {'cpu': 'percent'})
        assert module_history_fields('loose') == {'cpu': {'label': 'cpu', 'unit': ''}}

    def test_a_nameless_field_is_dropped(self, fake_module):
        fake_module('blank', lambda lang, var_dir='': {'': {'label': 'nothing'}})
        assert module_history_fields('blank') == {}

    def test_a_module_that_does_not_exist_is_an_empty_map(self):
        """History holds records from modules that have since been removed."""
        assert module_history_fields('no_such_watchful_anywhere') == {}

    def test_a_name_that_is_not_a_module_name_is_never_imported(self):
        """The module name reaches here from a history record, which is data. It composes an
        import path, so anything that could climb out of `watchfuls.` is refused rather than
        resolved."""
        for bad in ('', '   ', '_private', 'os.path', '../lib', 'lib.security'):
            assert module_history_fields(bad) == {}


class TestTheModuleThatNeededIt:

    def test_snmp_names_every_metric_its_profiles_can_record(self):
        fields = module_history_fields('snmp', 'es_ES')
        assert 'cpu_user' in fields and fields['cpu_user']['unit'] == '%'
        assert fields['cpu_user']['label'] != 'cpu_user', 'the label was not translated'

    def test_what_a_machine_IS_is_not_offered_as_a_series(self):
        """A name and a model identify the thing being charted; a chart of them would be a
        chart of nothing."""
        fields = module_history_fields('snmp')
        assert 'sys_name' not in fields and 'uptime' in fields

    def test_the_static_declaration_of_a_module_is_not_disturbed(self):
        """Every other watchful keeps exactly the fields its schema declares."""
        from lib.core.history.service import history_meta
        modules_dir = os.path.join(SRC, 'watchfuls')
        assert set(history_meta(modules_dir, 'cpu', 'en_EN').get('fields') or {}) == {'used'}
