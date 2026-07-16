#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The notification-event registry (lib.core.notify.events): each domain that publishes
notifications declares them in a ``notify_events`` module; the core discovers them, and
events can also be registered manually."""

from lib.core.notify import events


class TestDiscovery:
    def test_discovers_builtin_domain_events(self):
        keys = {e['key'] for e in events.discover_events()}
        # monitoring publishes down/recovery/warn, syslog publishes syslog, events → event
        assert {'down', 'recovery', 'warn', 'syslog', 'event'} <= keys

    def test_events_are_ordered_and_deduped(self):
        evs = events.events()
        keys = [e['key'] for e in evs]
        assert keys == sorted(set(keys), key=keys.index)          # no duplicates
        orders = [e['order'] for e in evs]
        assert orders == sorted(orders)                           # ordered by 'order'

    def test_descriptors_carry_source_and_label(self):
        by_key = {e['key']: e for e in events.events()}
        assert by_key['down']['source'] == 'monitoring'
        assert by_key['down']['label_key'] == 'notif_event_down'
        assert by_key['event']['source'] == 'events'

    def test_matrix_subset_excludes_rule_driven_event(self):
        # 'event' is rule-driven (channels chosen per rule) → not an auto-routing matrix kind.
        mk = set(events.matrix_event_keys())
        assert {'down', 'recovery', 'warn', 'syslog'} <= mk
        assert 'event' not in mk

    def test_ui_matrix_hides_compat_only_kinds(self):
        # 'syslog' stays a matrix kind (keeps its config keys) but is hidden from the routing
        # grid (ui=False) — no active dispatcher; a live control would mislead.
        ui = {e['key'] for e in events.ui_matrix_events()}
        assert {'down', 'recovery', 'warn'} <= ui
        assert 'syslog' not in ui
        assert 'syslog' in set(events.matrix_event_keys())


class TestManualRegistration:
    def test_register_and_override(self):
        events.register_event({'key': 'zz_probe', 'source': 'manual',
                               'label_key': 'x', 'matrix': True, 'order': 500})
        try:
            assert 'zz_probe' in events.event_keys()
            # manual registration wins over a same-key discovery/default
            events.register_event({'key': 'zz_probe', 'source': 'manual2',
                                   'label_key': 'x', 'matrix': False, 'order': 500})
            by_key = {e['key']: e for e in events.events()}
            assert by_key['zz_probe']['source'] == 'manual2'
            assert 'zz_probe' not in events.matrix_event_keys()
        finally:
            events._MANUAL.pop('zz_probe', None)

    def test_invalid_descriptor_ignored(self):
        events.register_event({'no_key': 'x'})
        assert None not in events.event_keys()


class TestMatrixIsFullyDynamic:
    """The routing matrix has a single source of truth: the notify-event registry × channels.
    It must NOT be duplicated as static ``notifications|{channel}_on_{kind}`` keys in spec.py —
    those cells are dynamic (stored per-cell in the DB when ticked, default off at dispatch)."""

    def test_no_static_matrix_keys_in_spec(self):
        from lib.config.spec import CFG_BY_PATH
        assert not [p for p in CFG_BY_PATH
                    if p.startswith('notifications|') and '_on_' in p]

    def test_builtin_kinds_come_from_the_registry(self):
        # The kinds that USED to be hard-listed now come purely from discovery.
        assert {'down', 'recovery', 'warn', 'syslog'} <= set(events.matrix_event_keys())
