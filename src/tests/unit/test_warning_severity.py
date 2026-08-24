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

            def add(self, kind, module, item, message, also=''):
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

            def add(self, kind, module, item, message, also=''):
                self.added.append(kind)

        m = Monitor.__new__(Monitor)
        m._notifier = _Notifier()
        m.send_message('host unreachable', status=False, module='ping', item='web01')
        assert m._notifier.added == ['down']


class TestModuleBaseEmitCarriesSeverity:
    """`ModuleBase._emit` records a result AND notifies. It passes `send_msg=False`, which
    disables the monitor's own digest path — so that explicit send is the ONLY notification.
    Dropping the severity there made a soft threshold breach paint amber in the UI while
    paging someone as if the thing were down. Four watchfuls carried that copy."""

    def _module(self):
        from lib.modules import ModuleBase

        class _M(ModuleBase):
            def __init__(self):                      # skip the real __init__
                self.sent = []
                self.recorded = []

            name_module = 'demo'

            class _DR:
                def __init__(self, out):
                    self._out = out

                def set(self, key, status, message, send_msg=True, other_data=None,
                        severity=None, name=''):
                    self._out.append((key, status, severity, send_msg))

            @property
            def dict_return(self):
                return self._DR(self.recorded)

            def get_conf(self, *_a, **_k):
                return 'web01'

            def check_status(self, *_a, **_k):
                return True                          # force the notification path

            def send_message(self, message, status=None, item='', severity='', kind=''):
                self.sent.append((message, status, item, severity))

        return _M()

    def test_a_warning_is_notified_as_a_warning(self):
        m = self._module()
        m._emit('web01/cpu', False, 'cpu high', {'used': 91}, severity='warning')
        assert m.sent == [('cpu high', False, 'web01', 'warning')]

    def test_the_severity_also_reaches_the_recorded_result(self):
        m = self._module()
        m._emit('web01/cpu', False, 'cpu high', severity='warning')
        assert m.recorded == [('web01/cpu', False, 'warning', False)]

    def test_a_hard_failure_still_notifies_without_severity(self):
        """No severity must stay a plain down — the fix must not turn everything amber."""
        m = self._module()
        m._emit('web01/cpu', False, 'unreachable')
        assert m.sent == [('unreachable', False, 'web01', '')]

    def test_the_monitor_would_route_that_pair_as_warn_and_down(self):
        """Ties the module side to the routing side, so the two cannot drift apart."""
        from lib.services.monitoring.monitor import Monitor
        assert Monitor._alert_kind(False, 'warning') == 'warn'
        assert Monitor._alert_kind(False, '') == 'down'


class TestEmitChangeMsgGate:
    """`change_msg` switches the notify gate to check_status_custom, which also fires when
    the REASON changes. Without it a failure that mutates ("connection refused" →
    "timeout") stays silent behind an unchanged "still down" — the module knows something
    new, nobody is told."""

    def _module(self, changed=False, custom=True):
        from lib.modules import ModuleBase

        class _M(ModuleBase):
            def __init__(self):
                self.sent = []
                self.gates = []

            name_module = 'demo'

            class _DR:
                def set(self, *_a, **_k):
                    return True

            @property
            def dict_return(self):
                return self._DR()

            def get_conf(self, *_a, **_k):
                return 'db1'

            def check_status(self, *_a, **_k):
                self.gates.append('plain')
                return changed

            def check_status_custom(self, status, key, status_msg):
                self.gates.append(('custom', status_msg))
                return custom

            def send_message(self, message, status=None, item='', severity='', kind=''):
                self.sent.append(message)

        return _M()

    def test_without_change_msg_it_uses_the_plain_gate(self):
        m = self._module(changed=False)
        m._emit('db1', False, 'down')
        assert m.gates == ['plain'] and m.sent == []

    def test_with_change_msg_it_uses_the_custom_gate(self):
        m = self._module(changed=False, custom=True)
        m._emit('db1', False, 'down', change_msg='timeout')
        assert m.gates == [('custom', 'timeout')]
        assert m.sent == ['down'], 'a changed reason must re-alert even with an unchanged status'

    def test_the_custom_gate_can_still_stay_quiet(self):
        """Same status AND same reason → no repeat alert every cycle."""
        m = self._module(changed=False, custom=False)
        m._emit('db1', False, 'down', change_msg='timeout')
        assert m.sent == []

    def test_an_empty_change_msg_still_selects_the_custom_gate(self):
        """'' is a legitimate reason (no detail); only None means "use the plain gate"."""
        m = self._module(custom=True)
        m._emit('db1', False, 'down', change_msg='')
        assert m.gates == [('custom', '')]


class TestTheSeverityRuleHasOneHome:
    """The rule lived as two identical copies — in the result structure and in the store
    that persists it. A rule about severity is the wrong thing to keep two of: add a third
    level and one copy goes on flattening it to 'error', which is how a warning ends up
    paging someone at 3am."""

    def test_the_store_uses_the_canonical_rule(self):
        from lib.modules.dict_return_check import norm_severity
        from lib.services.monitoring.check_state import store
        assert store._norm_severity is norm_severity, (
            'check_state/store.py must import the rule, not restate it')

    def test_the_result_structure_uses_it_too(self):
        from lib.modules.dict_return_check import ReturnModuleCheck, norm_severity
        assert ReturnModuleCheck._norm_severity is norm_severity

    def test_the_rule_itself(self):
        from lib.modules.dict_return_check import norm_severity
        assert norm_severity('warning', False) == 'warning'
        assert norm_severity('WARNING', False) == 'warning'    # case-insensitive
        assert norm_severity(None, False) == 'error'           # unspecified non-OK
        assert norm_severity('anything', False) == 'error'
        assert norm_severity('warning', True) == ''            # OK carries no severity

    def test_a_third_level_would_change_both_sides_at_once(self):
        """The point of the unification, stated as a test: whatever the rule returns, both
        surfaces return the same thing for the same input."""
        from lib.modules.dict_return_check import ReturnModuleCheck
        from lib.services.monitoring.check_state import store
        for sev, ok in (('warning', False), ('error', False), (None, False),
                        ('warning', True), ('', True)):
            assert store._norm_severity(sev, ok) == ReturnModuleCheck._norm_severity(sev, ok)



class TestAModuleNamingItsOwnKind:
    """A module may say "this failure is a kind of its own" — and two rules keep it safe.

    A matrix cell is stored only when somebody ticks it and reads false until then, so a kind
    the registry has never heard of routes to NO channel at all: a typo would be an alert that
    silently stops arriving, which is the exact failure this codebase keeps finding. And a
    recovery is a recovery wherever recoveries go — routing one as "unreachable" would put a
    green message under a red heading.
    """

    def _notifier(self):
        class _N:
            def __init__(self):
                self.added = []

            def add(self, kind, module, item, message, also=''):
                self.added.append((kind, also))
        return _N()

    def _monitor(self):
        m = Monitor.__new__(Monitor)
        m._notifier = self._notifier()
        return m

    def test_a_registered_kind_travels_beside_the_ordinary_one(self):
        m = self._monitor()
        m.send_message('no answer', status=False, module='snmp', item='pve02',
                       kind='snmp_unreachable')
        assert m._notifier.added == [('down', 'snmp_unreachable')]

    def test_a_kind_nobody_declared_is_dropped(self):
        """…and the alert still goes out as a plain down. The alternative is an alert routed
        by a cell that cannot exist, which is silence."""
        m = self._monitor()
        m.send_message('no answer', status=False, module='snmp', item='pve02',
                       kind='snmp_unreachabl')       # one letter short
        assert m._notifier.added == [('down', '')]

    def test_a_recovery_never_carries_it(self):
        m = self._monitor()
        m.send_message('back', status=True, module='snmp', item='pve02',
                       kind='snmp_unreachable')
        assert m._notifier.added == [('recovery', '')]

    def test_no_kind_is_the_ordinary_case(self):
        m = self._monitor()
        m.send_message('down', status=False, module='ping', item='web01')
        assert m._notifier.added == [('down', '')]

    def test_the_kind_the_snmp_module_uses_is_the_one_it_declares(self):
        """Two files — the manifest that declares the event and the sampler that sends it —
        and a rename in one would be an alert routed by a cell nobody can tick."""
        from lib.core.snmp.manifest import KIND_UNREACHABLE, NOTIFY_EVENTS
        from lib.core.notify import events as _events
        assert [e['key'] for e in NOTIFY_EVENTS] == [KIND_UNREACHABLE]
        assert KIND_UNREACHABLE in {e['key'] for e in _events.events()}, (
            'declared and not discovered: the routing screen has no row for it')

    def test_it_is_worded_and_marked_like_every_other_event(self):
        """A row with no label is a checkbox nobody can identify, and a message with no icon
        is the one that looks broken next to the others."""
        from lib.core.notify import formatting
        from lib.core.snmp.manifest import KIND_UNREACHABLE
        assert formatting.EVENT_ICON.get(KIND_UNREACHABLE)
        key = formatting.EVENT_LABEL_KEY.get(KIND_UNREACHABLE)
        assert key
        for lang in ('es_ES', 'en_EN'):
            mod = __import__(f'lib.i18n.lang.{lang}', fromlist=['x'])
            words = getattr(mod, 'TEXT', None) or getattr(mod, 'LANG', None) or {}
            found = key in words or any(key in v for v in words.values()
                                        if isinstance(v, dict))
            assert found, f'{key} is not worded in {lang}'
