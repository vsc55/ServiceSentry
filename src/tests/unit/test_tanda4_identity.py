#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure halves of the 2026-10-12 audit's fourth batch — no app, no database, no HTTP.

A forged CSRF token, SCIM bearer, TOTP code or WebAuthn challenge carrying a non-ASCII
character made `hmac.compare_digest` raise instead of answering no (an anonymous 500); a
published default dashboard dropped the core widgets' own filters; the certificate scanner
ignored a check's own window, a bound device's address and a switched-off module.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lib.core.health.alert_state import AlertState
from lib.core.health.cert_scan import CertExpiryScanner, enumerate_targets
from lib.core.mfa import totp, webauthn
from lib.core.overview.service import normalize_layout
from lib.providers.scim.service import bearer_token_ok
from lib.security import csrf


class TestNonAsciiSecretsAnswerNo:

    def test_csrf_token(self):
        req = SimpleNamespace(headers={csrf.HEADER_NAME: 'café'}, form={})
        assert csrf.is_valid(req, {csrf.SESSION_KEY: 'a' * 64}) is False

    def test_scim_bearer(self):
        assert bearer_token_ok('Bearer café', 'x' * 40, 32) is False

    def test_totp_code_in_another_script(self):
        # Arabic-Indic digits: `isdigit()` says yes, `compare_digest` used to raise.
        assert totp.verify(totp.secret_new(), '١٢٣٤٥٦') is None

    def test_webauthn_challenge(self):
        raw = json.dumps({'type': 'webauthn.get', 'challenge': 'café',
                          'origin': 'https://panel.example.test'}).encode()
        with pytest.raises(webauthn.CeremonyError):       # refused, not a TypeError
            webauthn._client_data(raw, 'webauthn.get', 'abc', 'https://panel.example.test')  # noqa: SLF001


class TestPublishedDefaultKeepsFilters:

    def test_core_widget_filters_survive(self):
        out = normalize_layout([{'id': 'alerts', 'cols': 2, 'sev': 'warn'},
                                {'id': 'servers_list', 'cols': 4, 'srvf': 'down', 'modf': 'ping'},
                                {'id': 'syslog', 'cols': 2, 'slsrc': 'src-1'}])
        assert out[0]['sev'] == 'warn'
        assert (out[1]['srvf'], out[1]['modf']) == ('down', 'ping')
        assert out[2]['slsrc'] == 'src-1'

    def test_a_junk_width_is_a_default_not_a_crash(self):
        assert normalize_layout([{'id': 'a', 'cols': 'wide'}])[0]['cols'] == 2


class TestCertScanner:

    def test_a_switched_off_module_is_not_scanned(self):
        cfg = {'ssl_cert': {'enabled': False, 'list': {'a': {'host': 'h.example.test'}}}}
        assert enumerate_targets(cfg) == []
        cfg['ssl_cert']['list']['a']['enabled'] = 'false'
        cfg['ssl_cert']['enabled'] = True
        assert enumerate_targets(cfg) == []

    def test_a_bound_device_address_wins_over_a_stale_host(self):
        cfg = {'ssl_cert': {'list': {'a': {'host': 'old.example.test', 'device_uid': 'd1'}}}}
        t = enumerate_targets(cfg, device_address=lambda uid: '10.0.0.9' if uid == 'd1' else None)
        assert t[0]['host'] == '10.0.0.9'

    def test_a_checks_own_window_is_honoured(self):
        sent = []
        sc = CertExpiryScanner(
            targets_provider=lambda: [{'key': 'a', 'label': 'A', 'warn_days': 60}],
            dispatch=lambda kind, **kw: sent.append(kw), days_fn=lambda _t: 45,
            config_getter=lambda: {'notify_expiry': True, 'warn_days': 21},
            text_fn=lambda key, *a: key, state=AlertState())
        assert sc.evaluate_once(now=0) == {'a': 45}
        assert sent

