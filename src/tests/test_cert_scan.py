#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Certificate-expiry scanner (lib.core.health.cert_scan): target enumeration from
the ssl_cert config and once-per-severity cert_expiring notifications."""

from lib.core.health.cert_scan import enumerate_targets, CertExpiryScanner


class TestEnumerate:
    def test_inline_and_defaults(self):
        cfg = {'ssl_cert': {'warning_days': 30, 'list': {
            'a': {'host': 'a.example', 'port': 8443, 'server_name': 'sni.example'},
            'b': {'host': 'b.example'},                       # port → 443, warn → module 30
        }}}
        ts = {t['key']: t for t in enumerate_targets(cfg)}
        assert ts['a']['port'] == 8443 and ts['a']['server_name'] == 'sni.example'
        assert ts['b']['port'] == 443 and ts['b']['warn_days'] == 30
        assert ts['b']['server_name'] == 'b.example'          # sni defaults to host

    def test_host_uid_resolved_via_store(self):
        cfg = {'ssl_cert': {'list': {'h': {'host_uid': 'uid-1', 'port': 443}}}}
        ts = enumerate_targets(cfg, host_address=lambda uid: '10.0.0.5' if uid == 'uid-1' else None)
        assert ts[0]['host'] == '10.0.0.5'

    def test_disabled_skipped_and_per_item_warn(self):
        cfg = {'ssl_cert': {'list': {
            'on':  {'host': 'x', 'warning_days': 7},
            'off': {'host': 'y', 'enabled': False},
        }}}
        ts = {t['key']: t for t in enumerate_targets(cfg, default_warn=21)}
        assert 'off' not in ts
        assert ts['on']['warn_days'] == 7

    def test_no_ssl_cert_config(self):
        assert enumerate_targets({}) == []


def _make(days_map, *, enabled=True, warn=21, leader=True):
    targets = [{'key': k, 'label': k, 'host': k, 'port': 443,
                'server_name': k, 'verify': True, 'warn_days': warn} for k in days_map]
    emitted = []
    sc = CertExpiryScanner(
        targets_provider=lambda: targets,
        dispatch=lambda kind, **f: emitted.append((f.get('status'), f.get('item'))),
        config_getter=lambda: {'notify_expiry': enabled, 'warn_days': warn},
        days_fn=lambda t: days_map[t['key']],
        is_leader=lambda: leader,
    )
    return sc, emitted, days_map


class TestScanner:
    def test_disabled_never_emits(self):
        sc, emitted, _ = _make({'a': 3}, enabled=False)
        sc.evaluate_once(now=0.0)
        assert emitted == []

    def test_not_leader_never_emits(self):
        sc, emitted, _ = _make({'a': 3}, leader=False)
        sc.evaluate_once(now=0.0)
        assert emitted == []

    def test_healthy_cert_not_alerted(self):
        sc, emitted, _ = _make({'a': 100}, warn=21)
        sc.evaluate_once(now=0.0)
        assert emitted == [] and 'a' not in sc._alerted

    def test_expiring_alerts_once(self):
        sc, emitted, _ = _make({'a': 5}, warn=21)
        sc.evaluate_once(now=0.0)
        sc.evaluate_once(now=1.0)                    # still expiring → no re-alert
        assert emitted == [('Expiring', 'a')]

    def test_escalates_expiring_to_expired(self):
        sc, emitted, days = _make({'a': 5}, warn=21)
        sc.evaluate_once(now=0.0)                    # EXPIRING
        days['a'] = -2
        sc.evaluate_once(now=1.0)                    # crosses to EXPIRED → one more alert
        assert emitted == [('Expiring', 'a'), ('Expired', 'a')]

    def test_recovery_rearms(self):
        sc, emitted, days = _make({'a': 5}, warn=21)
        sc.evaluate_once(now=0.0)                    # EXPIRING
        days['a'] = 200
        sc.evaluate_once(now=1.0)                    # renewed → re-arm (no alert)
        days['a'] = 4
        sc.evaluate_once(now=2.0)                    # expiring again → alerts again
        assert emitted == [('Expiring', 'a'), ('Expiring', 'a')]

    def test_unreachable_leaves_state(self):
        sc, emitted, days = _make({'a': 5}, warn=21)
        sc.evaluate_once(now=0.0)                    # EXPIRING
        days['a'] = None                             # unreachable
        sc.evaluate_once(now=1.0)
        assert emitted == [('Expiring', 'a')] and sc._alerted.get('a') == 'expiring'
