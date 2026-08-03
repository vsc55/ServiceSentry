#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entra client-secret expiry scanner: warning transitions + unattended rotation margin.

``SecretExpiryScanner.evaluate_once`` is pure decision logic (Graph/threads injected), so
every branch is exercised here without network: it must warn once per severity, re-arm when
the secret is renewed, rotate BEFORE warning once inside the margin, and still warn when a
rotation attempt fails.
"""

import datetime

from lib.core.health.secret_scan import SecretExpiryScanner, days_left, parse_expiry

NOW = 1_700_000_000.0


def iso_in(days: float) -> str:
    """ISO-8601 timestamp *days* from NOW (UTC, 'Z' suffix like Graph returns)."""
    dt = datetime.datetime.fromtimestamp(NOW + days * 86400, datetime.timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def make(cfg, *, rotate=None, saved=None, events=None, leader=True):
    """Scanner wired to in-memory fakes; returns (scanner, events, saved)."""
    events = events if events is not None else []
    saved = saved if saved is not None else []

    def _rotate():
        if rotate is None:
            raise RuntimeError('rotation not available')
        return rotate()

    sc = SecretExpiryScanner(
        config_getter=lambda: cfg,
        dispatch=lambda kind, **f: events.append((kind, f)),
        rotate_fn=_rotate,
        save_fn=lambda s, e: saved.append((s, e)),
        is_leader=lambda: leader,
        text_fn=lambda key, *a: key,          # keys, not translations — assert on the key
    )
    return sc, events, saved


BASE = {'enabled': True, 'secret_notify_expiry': True, 'secret_warn_days': 30,
        'secret_auto_rotate': False, 'secret_rotate_days': 15}


class TestExpiryHelpers:

    def test_parse_expiry_handles_z_suffix(self):
        assert parse_expiry('2027-01-15T10:20:30Z') is not None

    def test_parse_expiry_empty_or_garbage_is_none(self):
        assert parse_expiry('') is None
        assert parse_expiry('not-a-date') is None

    def test_days_left_counts_down(self):
        assert round(days_left(iso_in(10), now=NOW)) == 10
        assert round(days_left(iso_in(-3), now=NOW)) == -3


class TestWarning:

    def test_no_alert_while_outside_the_window(self):
        sc, ev, _ = make({**BASE, 'secret_expires_at': iso_in(90)})
        assert sc.evaluate_once(now=NOW)['alert'] == ''
        assert ev == []

    def test_warns_once_inside_the_window(self):
        sc, ev, _ = make({**BASE, 'secret_expires_at': iso_in(10)})
        assert sc.evaluate_once(now=NOW)['alert'] == 'expiring'
        assert ev[0][0] == 'secret_expiring'
        # second pass at the same severity must NOT re-alert
        assert sc.evaluate_once(now=NOW)['alert'] == ''
        assert len(ev) == 1

    def test_escalates_from_expiring_to_expired(self):
        cfg = {**BASE, 'secret_expires_at': iso_in(5)}
        sc, ev, _ = make(cfg)
        sc.evaluate_once(now=NOW)
        cfg['secret_expires_at'] = iso_in(-1)          # now past due
        assert sc.evaluate_once(now=NOW)['alert'] == 'expired'
        assert [k for k, _ in ev] == ['secret_expiring', 'secret_expiring']

    def test_rearms_after_renewal(self):
        cfg = {**BASE, 'secret_expires_at': iso_in(5)}
        sc, ev, _ = make(cfg)
        sc.evaluate_once(now=NOW)
        cfg['secret_expires_at'] = iso_in(200)         # renewed
        sc.evaluate_once(now=NOW)
        cfg['secret_expires_at'] = iso_in(5)           # close again → alerts again
        assert sc.evaluate_once(now=NOW)['alert'] == 'expiring'
        assert len(ev) == 2

    def test_unknown_expiry_does_nothing(self):
        sc, ev, _ = make({**BASE, 'secret_expires_at': ''})
        assert sc.evaluate_once(now=NOW) == {}
        assert ev == []

    def test_disabled_oidc_or_both_toggles_off_does_nothing(self):
        sc, ev, _ = make({**BASE, 'enabled': False, 'secret_expires_at': iso_in(1)})
        assert sc.evaluate_once(now=NOW) == {}
        sc2, ev2, _ = make({**BASE, 'secret_notify_expiry': False,
                            'secret_expires_at': iso_in(1)})
        assert sc2.evaluate_once(now=NOW) == {}
        assert ev == [] and ev2 == []

    def test_non_leader_never_alerts(self):
        sc, ev, _ = make({**BASE, 'secret_expires_at': iso_in(1)}, leader=False)
        assert sc.evaluate_once(now=NOW) == {}
        assert ev == []


class TestRotation:

    def test_rotates_inside_the_margin_and_does_not_warn(self):
        cfg = {**BASE, 'secret_auto_rotate': True, 'secret_expires_at': iso_in(10)}
        sc, ev, saved = make(cfg, rotate=lambda: {'secret': 'NEW', 'expires_at': iso_in(365)})
        rep = sc.evaluate_once(now=NOW)
        assert rep['rotated'] is True and rep['alert'] == ''
        assert saved == [('NEW', iso_in(365))]
        assert [k for k, _ in ev] == ['secret_rotated']

    def test_does_not_rotate_outside_the_margin(self):
        cfg = {**BASE, 'secret_auto_rotate': True, 'secret_expires_at': iso_in(20)}
        sc, ev, saved = make(cfg, rotate=lambda: {'secret': 'NEW', 'expires_at': iso_in(365)})
        rep = sc.evaluate_once(now=NOW)
        assert rep['rotated'] is False and saved == []
        assert [k for k, _ in ev] == ['secret_expiring']   # 20d ≤ warn 30 → warns only

    def test_failed_rotation_still_warns(self):
        cfg = {**BASE, 'secret_auto_rotate': True, 'secret_expires_at': iso_in(3)}
        sc, ev, saved = make(cfg, rotate=None)             # rotate raises
        rep = sc.evaluate_once(now=NOW)
        assert rep['rotated'] is False and saved == []
        assert [k for k, _ in ev] == ['secret_expiring']

    def test_empty_secret_from_graph_is_treated_as_failure(self):
        cfg = {**BASE, 'secret_auto_rotate': True, 'secret_expires_at': iso_in(3)}
        sc, ev, saved = make(cfg, rotate=lambda: {'secret': '', 'expires_at': iso_in(365)})
        assert sc.evaluate_once(now=NOW)['rotated'] is False
        assert saved == [] and [k for k, _ in ev] == ['secret_expiring']

    def test_rotation_works_with_notify_off(self):
        """auto_rotate alone (no warnings configured) still rotates."""
        cfg = {**BASE, 'secret_notify_expiry': False, 'secret_auto_rotate': True,
               'secret_expires_at': iso_in(2)}
        sc, ev, saved = make(cfg, rotate=lambda: {'secret': 'NEW', 'expires_at': iso_in(365)})
        assert sc.evaluate_once(now=NOW)['rotated'] is True
        assert saved == [('NEW', iso_in(365))]
