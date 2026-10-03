#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Teams tab token has to come from THIS tenant (lib.providers.entraid.tab_sso).

Microsoft signs every tenant's tokens with the same keys, so a valid signature, our audience
and *a* Microsoft issuer is what a token from any organisation looks like once the app
registration is multi-tenant. The check used to stop at the issuer's prefix; ``tid`` was never
compared with the configured tenant. No Flask, no network: the JWT library and the discovery
fetch are replaced.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lib.providers.entraid import tab_sso

_OURS = '11111111-2222-3333-4444-555555555555'
_THEIRS = '99999999-8888-7777-6666-555555555555'


def _claims(tid=_OURS, iss=None):
    return {'tid': tid, 'iss': iss or f'https://login.microsoftonline.com/{tid}/v2.0',
            'preferred_username': 'ann@corp.example', 'oid': 'oid-1'}


class TestCheckTenant:

    def test_our_tenant_v2_issuer_passes(self):
        tab_sso.check_tenant(_claims(), _OURS)

    def test_our_tenant_v1_issuer_passes(self):
        tab_sso.check_tenant(_claims(iss=f'https://sts.windows.net/{_OURS}/'), _OURS)

    def test_the_guid_is_compared_case_insensitively(self):
        tab_sso.check_tenant(_claims(tid=_OURS.upper(),
                                     iss=f'https://login.microsoftonline.com/{_OURS}/v2.0'),
                             _OURS)

    def test_another_tenant_is_refused(self):
        with pytest.raises(ValueError):
            tab_sso.check_tenant(_claims(tid=_THEIRS), _OURS)

    def test_our_tid_with_another_tenants_issuer_is_refused(self):
        with pytest.raises(ValueError):
            tab_sso.check_tenant(
                _claims(iss=f'https://login.microsoftonline.com/{_THEIRS}/v2.0'), _OURS)

    def test_a_token_with_no_tid_is_refused(self):
        c = _claims()
        c.pop('tid')
        with pytest.raises(ValueError):
            tab_sso.check_tenant(c, _OURS)

    @pytest.mark.parametrize('authority', ['common', 'organizations', 'consumers', ''])
    def test_a_multi_tenant_authority_is_not_a_tenant(self, authority):
        with pytest.raises(ValueError):
            tab_sso.check_tenant(_claims(), authority)

    def test_a_domain_tenant_is_resolved_to_its_guid(self):
        tab_sso._TENANT_CACHE.clear()
        with patch.object(tab_sso, '_fetch_tenant_guid', return_value=_OURS) as fetch:
            tab_sso.check_tenant(_claims(), 'corp.onmicrosoft.com')
            tab_sso.check_tenant(_claims(), 'CORP.onmicrosoft.com')
            with pytest.raises(ValueError):
                tab_sso.check_tenant(_claims(tid=_THEIRS), 'corp.onmicrosoft.com')
        assert fetch.call_count == 1, 'resolved once, then cached'

    def test_a_malformed_tenant_is_refused_before_any_fetch(self):
        with patch.object(tab_sso, '_fetch_tenant_guid') as fetch:
            with pytest.raises(ValueError):
                tab_sso.tenant_guid('evil.example/../x')
        fetch.assert_not_called()


class TestValidateTabTokenChecksTheTenant:
    """The whole validation path, with the JWT library replaced: what decode() returns is a
    token that verified — and it must still be refused when it is another tenant's."""

    def _run(self, claims):
        fake_jwt = SimpleNamespace(decode=lambda *a, **k: dict(claims))
        fake_client = lambda _uri: SimpleNamespace(  # noqa: E731
            get_signing_key_from_jwt=lambda _t: SimpleNamespace(key='k'))
        with patch.object(tab_sso, '_HAS_JWT', True), \
             patch.object(tab_sso, '_jwt', fake_jwt, create=True), \
             patch.object(tab_sso, '_PyJWKClient', fake_client, create=True):
            return tab_sso.validate_tab_token('tok', _OURS, 'client-1')

    def test_a_token_from_our_tenant_is_accepted(self):
        assert self._run(_claims())['oid'] == 'oid-1'

    def test_a_token_from_another_tenant_is_refused(self):
        with pytest.raises(ValueError):
            self._run(_claims(tid=_THEIRS))
