#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overview checks-badge counting: warnings are tallied apart from hard errors.

Guards that a soft threshold breach (severity 'warning') shows on the Overview
checks widget as a warning, not folded into the error count (nor hidden)."""

import pytest

from lib.core.modules.overview_widget import (
    OVERVIEW_WIDGETS as MOD_WIDGETS, _mod_checks, _modules_list_rows)
from lib.core.hosts.overview_widget import OVERVIEW_WIDGETS as HOST_WIDGETS, _server_matches
from lib.core.overview.filters import parse_severity_filter, severity_matches
from lib.services.monitoring.overview_widget import checks_stat


class TestSeverityFilterParsing:

    @pytest.mark.parametrize('value, expected', [
        ('',              ('', '', False)),
        ('ge_warning',    ('warning', 'ge', False)),
        ('eq_warning',    ('warning', 'eq', False)),
        ('ge_error',      ('error', 'ge', False)),
        ('ge_warning+m',  ('warning', 'ge', True)),
        ('m',             ('', '', True)),
        ('virtual',       ('virtual', '', False)),
        ('physical+m',    ('physical', '', True)),
        ('error',         ('error', 'ge', False)),    # legacy
        ('warn',          ('warning', 'ge', False)),  # legacy
        ('errmaint',      ('error', 'ge', True)),      # legacy
    ])
    def test_parse(self, value, expected):
        assert parse_severity_filter(value) == expected

    def test_ge_covers_higher_levels_eq_does_not(self):
        # rank 2 = error, 1 = warning. '≥ warning' matches both; '= warning' only warning.
        assert severity_matches(2, 'warning', 'ge') and severity_matches(1, 'warning', 'ge')
        assert severity_matches(1, 'warning', 'eq') and not severity_matches(2, 'warning', 'eq')
        # error is the top level → ge and eq behave the same.
        assert severity_matches(2, 'error', 'ge') and severity_matches(2, 'error', 'eq')
        assert not severity_matches(1, 'error', 'ge')


def _filter_levels(widgets, widget_id):
    w = next(w for w in widgets if w['id'] == widget_id)
    flt = w['view']['filter']
    return [o['v'] for o in (flt.get('levels') or flt.get('options') or [])]


def _status(items):
    return {'cpu': {k: v for k, v in items.items()}}


class _FakeWA:
    def __init__(self, status, modules):
        self._status = status
        self._modules = modules

    def _read_check_status(self):
        return self._status

    def _load_modules(self):
        return self._modules


class TestModChecksCounts:

    def test_splits_warning_from_error(self):
        st = _status({
            'a': {'status': True},
            'b': {'status': False, 'severity': 'warning'},
            'c': {'status': False, 'severity': 'error'},
            'd': {'status': False},                     # no severity → hard error
        })
        assert _mod_checks(st, 'cpu') == {'total': 4, 'ok': 1, 'error': 2, 'warning': 1}

    def test_all_warnings_no_errors(self):
        st = _status({
            'a': {'status': False, 'severity': 'warning'},
            'b': {'status': False, 'severity': 'warning'},
        })
        r = _mod_checks(st, 'cpu')
        assert r['error'] == 0 and r['warning'] == 2 and r['ok'] == 0

    def test_missing_module_is_empty(self):
        assert _mod_checks({}, 'nope') == {'total': 0, 'ok': 0, 'error': 0, 'warning': 0}


class TestChecksStat:

    def test_errors_and_warnings_get_separate_badges(self):
        wa = _FakeWA(
            {'cpu': {'a': {'status': False, 'severity': 'warning'},
                     'b': {'status': False, 'severity': 'error'}}},
            {'cpu': {}})
        out = checks_stat(wa)
        keys = [b['key'] for b in out['badges']]
        assert out['accent'] == 'red'                       # a hard error dominates
        assert 'overview_has_errors' in keys and 'overview_has_warnings' in keys

    def test_only_warnings_read_amber(self):
        wa = _FakeWA(
            {'cpu': {'a': {'status': False, 'severity': 'warning'}}},
            {'cpu': {}})
        out = checks_stat(wa)
        assert out['accent'] == 'amber'
        assert [b['key'] for b in out['badges']] == ['overview_has_warnings']

    def test_all_ok(self):
        wa = _FakeWA({'cpu': {'a': {'status': True}}}, {'cpu': {}})
        out = checks_stat(wa)
        assert out['accent'] == 'green'
        assert out['badges'][0]['key'] == 'overview_all_ok'


class TestSeverityFilter:

    def _wa(self):
        # cpu: a module at warning level, ping: at error level (worse).
        return _FakeWA(
            {'cpu':  {'a': {'status': False, 'severity': 'warning'}},
             'ping': {'b': {'status': False, 'severity': 'error'}}},
            {'cpu':  {'enabled': True, 'list': {'a': {}}},
             'ping': {'enabled': True, 'list': {'b': {}}}})

    def test_exact_warning_excludes_error(self):
        # '= warning' → only warning-level modules (error is a higher level).
        assert [r['name'] for r in _modules_list_rows(self._wa(), 'eq_warning')] == ['cpu']

    def test_ge_warning_includes_error(self):
        # '≥ warning' → warning and everything more severe (error).
        assert sorted(r['name'] for r in _modules_list_rows(self._wa(), 'ge_warning')) == ['cpu', 'ping']

    def test_error_level(self):
        assert [r['name'] for r in _modules_list_rows(self._wa(), 'ge_error')] == ['ping']

    def test_legacy_values_still_work(self):
        # Saved dashboards used 'error'/'warn' — mapped onto the new scheme.
        assert [r['name'] for r in _modules_list_rows(self._wa(), 'error')] == ['ping']
        assert sorted(r['name'] for r in _modules_list_rows(self._wa(), 'warn')) == ['cpu', 'ping']

    def test_both_widgets_declare_severity_levels(self):
        # Adding a level is descriptor-only (overview_widget.py) — the toolbar builds the
        # control from view.filter.levels, so this is the single source to guard.
        assert {'warning', 'error'} <= set(_filter_levels(MOD_WIDGETS, 'modules_list'))
        assert {'warning', 'error'} <= set(_filter_levels(HOST_WIDGETS, 'servers_list'))
        # servers declares the maintenance union; modules do not.
        srv = next(w for w in HOST_WIDGETS if w['id'] == 'servers_list')['view']['filter']
        mod = next(w for w in MOD_WIDGETS if w['id'] == 'modules_list')['view']['filter']
        assert srv['kind'] == 'severity' and srv['maintenance'] is True
        assert mod['kind'] == 'severity' and mod['maintenance'] is False


class TestServerMatcher:

    _ROWS = [
        {'name': 'w',  'checks': {'warning': 1, 'error': 0}, 'status': 'warning', 'maintenance': False, 'virtual': False},
        {'name': 'e',  'checks': {'warning': 0, 'error': 1}, 'status': 'error',   'maintenance': False, 'virtual': True},
        {'name': 'ok', 'checks': {'warning': 0, 'error': 0}, 'status': 'ok',      'maintenance': False, 'virtual': False},
        {'name': 'm',  'checks': {'warning': 0, 'error': 0}, 'status': 'warning', 'maintenance': True,  'virtual': False},
    ]

    def _sel(self, level, op, maint):
        return [r['name'] for r in self._ROWS if _server_matches(r, level, op, maint)]

    def test_exact_warning_excludes_error_and_maintenance(self):
        assert self._sel('warning', 'eq', False) == ['w']

    def test_ge_warning_includes_error_but_not_maintenance(self):
        assert self._sel('warning', 'ge', False) == ['w', 'e']

    def test_maintenance_union_adds_maintenance_hosts(self):
        assert self._sel('warning', 'ge', True) == ['w', 'e', 'm']

    def test_maintenance_only(self):
        assert self._sel('', '', True) == ['m']

    def test_virtual_excludes_maintenance(self):
        assert self._sel('virtual', '', False) == ['e']
