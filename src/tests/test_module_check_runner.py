#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for lib/modules/check_runner — running one module's check() once.

Two features share this runner: the Servers "test" button and a module page's live refresh.
That makes its projection — which fields of a result survive a one-off run — a decision
about the MODULE RESULT CONTRACT, and the guard below is the point of this file: the
projection stopped carrying ``severity`` and nothing failed, it just quietly lost the field
that separates a warning from an outage.
"""

import inspect
from unittest.mock import patch

from lib.modules import check_runner
from lib.modules.dict_return_check import ReturnModuleCheck


def _run(results: dict) -> list:
    """Run the projection over a stub module that returns *results*."""
    class _Stub:
        def __init__(self, mon):
            self.mon = mon
            self.dict_return = type('D', (), {'list': results})()
        def check(self):
            return None
    mod = type('M', (), {'Watchful': _Stub})
    with patch.object(check_runner.importlib, 'import_module', return_value=mod):
        return check_runner.run_module_check('stub', {})


class TestTheProjectionMatchesTheContract:
    """Every field a result can carry is either projected or excluded on purpose."""

    def test_no_field_of_the_contract_is_lost_by_omission(self):
        # ReturnModuleCheck.set() IS the contract: what it writes is what a result has. A
        # projection that hand-copies a subset freezes the schema of the day it was written,
        # and the failure mode is not an error — it is silent data loss.
        written = set(inspect.signature(ReturnModuleCheck.set).parameters) - {'self', 'key'}
        written = {'send' if p == 'send_msg' else p for p in written}
        covered = set(check_runner.RESULT_FIELDS) | set(check_runner.RESULT_FIELDS_EXCLUDED)
        assert written - covered == set(), (
            f'fields of the result contract neither projected nor excluded: {written - covered}. '
            'Add them to RESULT_FIELDS, or to RESULT_FIELDS_EXCLUDED with a reason.')

    def test_nothing_is_projected_that_the_contract_does_not_write(self):
        written = {'send' if p == 'send_msg' else p
                   for p in inspect.signature(ReturnModuleCheck.set).parameters} - {'self'}
        assert set(check_runner.RESULT_FIELDS) - written == set()

    def test_the_exclusion_is_only_the_notify_gate(self):
        # A one-off run notifies nobody, so `send` is not part of its answer. Pinned so the
        # exclusion list stays a considered decision rather than a place to hide fields.
        assert check_runner.RESULT_FIELDS_EXCLUDED == ('send',)

    def test_every_projected_field_reaches_the_caller(self):
        out = _run({'k': {'status': False, 'severity': 'warning', 'message': 'm',
                          'name': 'n', 'other_data': {'x': 1}, 'send': True}})
        for field in check_runner.RESULT_FIELDS:
            assert field in out[0], field
        assert 'key' in out[0]

    def test_the_notify_gate_does_not_reach_the_caller(self):
        out = _run({'k': {'status': False, 'send': True}})
        assert 'send' not in out[0]


class TestASeveritySurvivesTheRun:
    """A warning must stay a warning when the check is run on demand.

    The bug this pins: a soft threshold breach (unused licences, a quota near its limit)
    came back indistinguishable from a hard failure, so a module page's live refresh painted
    it red while the monitor's stored result painted the very same check amber.
    """

    def test_a_warning_is_not_reported_as_a_failure(self):
        out = _run({'k': {'status': False, 'severity': 'warning', 'message': 'soft'}})
        assert out[0]['severity'] == 'warning'
        assert out[0]['status'] is False        # still not OK — just not an error

    def test_a_plain_failure_carries_no_severity(self):
        # An empty severity is what "this is an error" looks like: consumers turn anything
        # non-OK red unless told otherwise, so the absence has to stay an absence.
        out = _run({'k': {'status': False, 'message': 'hard'}})
        assert out[0]['severity'] == ''

    def test_a_field_the_module_never_set_reads_as_empty_not_missing(self):
        # A consumer that has to test for a key's existence will eventually forget, and the
        # branch it forgets is the amber one.
        out = _run({'k': {'status': True}})
        assert out[0]['severity'] == '' and out[0]['message'] == ''
        assert out[0]['name'] == '' and out[0]['other_data'] is None


class TestItRunsTheRealCheck:
    """A probe that took a different path would prove nothing about the scheduled run."""

    def test_it_refuses_a_module_without_a_watchful(self):
        mod = type('M', (), {})
        with patch.object(check_runner.importlib, 'import_module', return_value=mod):
            try:
                check_runner.run_module_check('stub', {})
            except ImportError as exc:
                assert 'Watchful' in str(exc)
            else:
                raise AssertionError('a module with no Watchful must not run silently')

    def test_a_non_dict_result_is_skipped_not_fatal(self):
        out = _run({'good': {'status': True}, 'bad': 'not a dict'})
        assert [r['key'] for r in out] == ['good']


class TestTheStandInIsAMonitor:

    def test_is_a_monitor(self):
        # Must satisfy ModuleBase's isinstance(obj, Monitor) check.
        import lib
        mon = check_runner.ProbeMonitor({}, None, None)
        assert isinstance(mon, lib.Monitor)
        assert mon.send_message('x', True) is None      # no-op, no Telegram
        # Signature must mirror Monitor.send_message: ModuleBase forwards module=/item=,
        # so a probe of any module that emits an alert must not TypeError.
        assert mon.send_message('x', True, module='process', item='web') is None
