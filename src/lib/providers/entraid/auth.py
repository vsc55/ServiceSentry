#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Microsoft Entra ID — tokens & tenant helpers.

App-only (client-credentials) tokens, interactive device-code sign-in, and pulling
the tenant out of a token / provider URL.  Pure: raises ``RuntimeError`` (provider
message) on failure; the web layer owns responses and device-flow state."""

from __future__ import annotations

import base64
import json as _json
import re as _re

import requests as _req

from lib.providers.entraid.client import AUTHORITY, DCF_CLIENT_ID, PROVISION_SCOPE


def tenant_from_provider_url(provider_url: str):
    """The tenant (id or domain) in an Entra OIDC provider URL
    (``…/login.microsoftonline.com/<tenant>/…``), or ``None`` if it isn't one."""
    m = _re.search(r'login\.microsoftonline\.com/([^/?#\s]+)', provider_url or '')
    return m.group(1) if m else None


def extract_tenant_id(token_body: dict) -> str:
    """Extract the tenant ID from a token response (tid claim, else the iss UUID)."""
    def _tid_from_jwt(jwt_str: str) -> str:
        try:
            payload = jwt_str.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            claims = _json.loads(base64.urlsafe_b64decode(payload))
            if claims.get('tid'):
                return claims['tid']
            m = _re.search(r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/',
                           claims.get('iss', ''), _re.I)
            if m:
                return m.group(1)
        except Exception:  # pylint: disable=broad-except
            pass
        return ''

    return (_tid_from_jwt(token_body.get('access_token', ''))
            or _tid_from_jwt(token_body.get('id_token', '')))


def app_token(tenant: str, client_id: str, client_secret: str,
              scope: str = 'https://graph.microsoft.com/.default') -> str:
    """Acquire an app-only (client-credentials) access token.  Raises
    ``RuntimeError`` with the provider message on failure."""
    tok = _req.post(
        f'{AUTHORITY}/{tenant}/oauth2/v2.0/token',
        data={'grant_type': 'client_credentials', 'client_id': client_id,
              'client_secret': client_secret, 'scope': scope},
        timeout=15).json()
    access_token = tok.get('access_token')
    if not access_token:
        raise RuntimeError(tok.get('error_description') or tok.get('error') or 'Token request failed')
    return access_token


def device_code_start(scope: str = PROVISION_SCOPE, client_id: str = DCF_CLIENT_ID) -> dict:
    """Begin the Device Code Flow; returns the raw devicecode response
    (``device_code``, ``user_code``, ``verification_uri``,
    ``verification_uri_complete``, ``expires_in``, ``interval``).  Raises
    ``RuntimeError`` with the provider message on failure."""
    resp = _req.post(f'{AUTHORITY}/common/oauth2/v2.0/devicecode',
                     data={'client_id': client_id, 'scope': scope}, timeout=15)
    if not resp.ok:
        b = resp.json() if resp.content else {}
        # May be empty — the web layer supplies its own i18n fallback message.
        raise RuntimeError(b.get('error_description') or '')
    return resp.json()


def device_code_poll(device_code: str, client_id: str = DCF_CLIENT_ID) -> dict:
    """Poll the token endpoint for a pending device-code flow; returns the raw
    token body (the caller inspects ``error`` / ``access_token``).  ``client_id``
    MUST match the one used to start the flow."""
    return _req.post(
        f'{AUTHORITY}/common/oauth2/v2.0/token',
        data={'client_id': client_id,
              'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
              'device_code': device_code}, timeout=15).json()
