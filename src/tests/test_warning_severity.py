#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Threshold-breach sensors route as ``warn``, not ``down``.

Guards the mechanism behind "high CPU / memory / near-expiry cert showed as DOWN
when it should be a warning": a soft threshold breach carries ``severity='warning'``
(the host is reachable) and the monitor maps that to the ``warn`` routing kind, while
a hard failure (no severity → 'error') stays ``down``.
"""

import pytest

from lib.modules.dict_return_check import ReturnModuleCheck
from lib.services.monitoring.monitor import Monitor


class TestSeverityNormalization:

    def test_warning_is_preserved_on_a_non_ok_result(self):
        r = ReturnModuleCheck()
        r.set('k', False, 'high cpu', severity='warning')
        assert r.get_severity('k') == 'warning'

    def test_non_ok_without_severity_defaults_to_error(self):
        r = ReturnModuleCheck()
        r.set('k', False, 'unreachable')
        assert r.get_severity('k') == 'error'

    def test_ok_result_has_no_severity(self):
        r = ReturnModuleCheck()
        r.set('k', True, 'fine', severity='warning')   # ignored for an OK status
        assert r.get_severity('k') == ''


class TestAlertKindMapping:

    @pytest.mark.parametrize('status, severity, kind', [
        (False, 'warning', 'warn'),    # soft threshold breach → warn
        (False, 'error',   'down'),    # hard failure → down
        (False, '',        'down'),    # unspecified non-OK → down
        (True,  '',        'recovery'),
    ])
    def test_kind(self, status, severity, kind):
        assert Monitor._alert_kind(status, severity) == kind


class TestSendMessageBridgeCarriesSeverity:

    def test_send_message_routes_a_warning_as_warn(self):
        class _Notifier:
            def __init__(self):
                self.added = []

            def add(self, kind, module, item, message):
                self.added.append((kind, module, item, message))

        m = Monitor.__new__(Monitor)          # skip heavy __init__
        m._notifier = _Notifier()
        m.send_message('high cpu', status=False, module='cpu', item='web01',
                       severity='warning')
        assert m._notifier.added == [('warn', 'cpu', 'web01', 'high cpu')]

    def test_send_message_without_severity_stays_down(self):
        class _Notifier:
            def __init__(self):
                self.added = []

            def add(self, kind, module, item, message):
                self.added.append(kind)

        m = Monitor.__new__(Monitor)
        m._notifier = _Notifier()
        m.send_message('host unreachable', status=False, module='ping', item='web01')
        assert m._notifier.added == ['down']
